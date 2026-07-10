import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Draft, Order, OrderStatus
from app.db.session import async_session
from app.services.handler_leads import push_to_handler_lead
from app.services.pipeline import OrderPipeline

logger = logging.getLogger(__name__)
router = Router()

_pending_edits: dict[int, int] = {}


def _order_keyboard(order_id: int, url: str, source: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Отправить", callback_data=f"oh:send:{order_id}"),
            InlineKeyboardButton(text="Пропустить", callback_data=f"oh:skip:{order_id}"),
        ],
        [
            InlineKeyboardButton(text="Править", callback_data=f"oh:edit:{order_id}"),
            InlineKeyboardButton(text="Открыть", url=url),
        ],
    ]
    if source == "kwork":
        rows[0].insert(
            1,
            InlineKeyboardButton(
                text="Kwork отклик", callback_data=f"oh:kwork:{order_id}"
            ),
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def notify_order_card(order: Order, draft_text: str) -> None:
    settings = get_settings()
    if not settings.bot_token or not settings.admin_id_list:
        return

    bot = Bot(token=settings.bot_token)
    reasons = order.match_reasons[:500]
    text = (
        f"<b>Заказ</b> [{order.source}] score {order.match_score:.0f}\n"
        f"<b>{order.title[:300]}</b>\n\n"
        f"{order.description[:800]}\n\n"
        f"<i>{reasons}</i>\n\n"
        f"<b>Черновик:</b>\n{draft_text[:2500]}"
    )
    kb = _order_keyboard(order.id, order.url, order.source)
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            logger.exception("Notify failed for %s", admin_id)

    async with async_session() as session:
        db_order = await session.get(Order, order.id)
        if db_order:
            db_order.status = OrderStatus.NOTIFIED
            pipeline = OrderPipeline(session)
            await pipeline.log_action(order.id, "notified", {})
            await session.commit()
    await bot.session.close()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "OrderHunter Assist\n\n"
        "Жду карточки заказов. Команды:\n"
        "/stats — воронка\n"
        "/help — справка"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Кнопки на карточке:\n"
        "• Отправить — отметить как отправленный (+ Handler lead если включён)\n"
        "• Kwork отклик — submit через API (Assist)\n"
        "• Править — пришлите новый текст ответом\n"
        "• Пропустить — скрыть заказ\n"
        "• Открыть — ссылка на площадку"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    from app.services.analytics import get_funnel

    async with async_session() as session:
        funnel = await get_funnel(session, days=7)
    if not funnel:
        await message.answer("Нет данных.")
        return
    lines = ["<b>Воронка 7 дней</b>"]
    for row in funnel:
        lines.append(
            f"{row['day']}: seen {row['seen']} → matched {row['matched']} → "
            f"notified {row['notified']} → sent {row['sent']}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data.startswith("oh:skip:"))
async def cb_skip(query: CallbackQuery) -> None:
    order_id = int(query.data.split(":")[2])
    async with async_session() as session:
        order = await session.get(Order, order_id)
        if order:
            order.status = OrderStatus.SKIPPED
            pipeline = OrderPipeline(session)
            await pipeline.log_action(order_id, "skipped", {})
        await session.commit()
    await query.answer("Пропущено")
    await query.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("oh:edit:"))
async def cb_edit(query: CallbackQuery) -> None:
    order_id = int(query.data.split(":")[2])
    _pending_edits[query.from_user.id] = order_id
    await query.answer()
    await query.message.answer("Пришлите новый текст отклика одним сообщением.")


@router.message(F.text)
async def on_text_edit(message: Message) -> None:
    order_id = _pending_edits.pop(message.from_user.id, None)
    if not order_id:
        return
    async with async_session() as session:
        draft = await session.scalar(
            select(Draft).where(Draft.order_id == order_id).order_by(Draft.id.desc())
        )
        if draft:
            draft.text = message.text
            await session.commit()
    await message.answer("Черновик обновлён. Нажмите «Отправить» на карточке.")


@router.callback_query(F.data.startswith("oh:send:"))
async def cb_send(query: CallbackQuery) -> None:
    order_id = int(query.data.split(":")[2])
    async with async_session() as session:
        order = await session.get(Order, order_id)
        draft = await session.scalar(
            select(Draft).where(Draft.order_id == order_id).order_by(Draft.id.desc())
        )
        if not order:
            await query.answer("Заказ не найден")
            return
        order.status = OrderStatus.SENT
        pipeline = OrderPipeline(session)
        await pipeline.log_action(order_id, "sent", {})
        await session.commit()
        if draft:
            await push_to_handler_lead(order, draft.text)
    await query.answer("Отмечено как отправлено")
    await query.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("oh:kwork:"))
async def cb_kwork(query: CallbackQuery) -> None:
    from app.connectors.kwork import KworkConnector

    order_id = int(query.data.split(":")[2])
    async with async_session() as session:
        order = await session.get(Order, order_id)
        draft = await session.scalar(
            select(Draft).where(Draft.order_id == order_id).order_by(Draft.id.desc())
        )
        if not order or not draft:
            await query.answer("Нет черновика")
            return
        raw = order.raw_json or "{}"
        import json

        data = json.loads(raw)
        project_id = data.get("project_id")
        if not project_id:
            await query.answer("Нет project_id")
            return
        price = order.budget_min_rub or 30000
        try:
            connector = KworkConnector()
            await connector.submit_offer(int(project_id), draft.text, price)
            order.status = OrderStatus.SENT
            pipeline = OrderPipeline(session)
            await pipeline.log_action(order_id, "sent", {"via": "kwork_api"})
            await session.commit()
            await push_to_handler_lead(order, draft.text)
            await query.answer("Отклик отправлен на Kwork")
        except Exception as e:
            logger.exception("Kwork submit failed")
            await query.answer(f"Ошибка: {e}", show_alert=True)
            return
    await query.message.edit_reply_markup(reply_markup=None)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp
