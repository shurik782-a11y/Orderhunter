import html
import json
import logging
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Draft, Order, OrderStatus
from app.db.session import async_session
from app.services.handler_leads import push_to_handler_lead
from app.services.monitor_state import monitor
from app.services.pipeline import OrderPipeline

logger = logging.getLogger(__name__)
router = Router()

_pending_edits: dict[int, int] = {}

BTN_STATUS = "📡 Статус"
BTN_STATS = "📊 Статистика"
BTN_QUEUE = "📋 Очередь"
BTN_SOURCES = "🔌 Источники"
BTN_PAUSE = "⏸ Пауза"
BTN_RESUME = "▶️ Искать"
BTN_HELP = "❓ Помощь"


def main_keyboard() -> ReplyKeyboardMarkup:
    pause_or_resume = BTN_RESUME if monitor.paused else BTN_PAUSE
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_STATS)],
            [KeyboardButton(text=BTN_QUEUE), KeyboardButton(text=BTN_SOURCES)],
            [KeyboardButton(text=pause_or_resume), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Меню OrderHunter…",
    )


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    admins = get_settings().admin_id_list
    return not admins or user_id in admins


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.astimezone(UTC).strftime("%H:%M UTC")


def _order_keyboard(order_id: int, url: str, source: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data=f"oh:send:{order_id}"),
            InlineKeyboardButton(text="⏭ Пропуск", callback_data=f"oh:skip:{order_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Править", callback_data=f"oh:edit:{order_id}"),
            InlineKeyboardButton(text="🔗 Открыть", url=url),
        ],
    ]
    if source == "kwork":
        rows.insert(
            1,
            [
                InlineKeyboardButton(
                    text="🚀 Kwork отклик", callback_data=f"oh:kwork:{order_id}"
                )
            ],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def notify_order_card(order: Order, draft_text: str) -> None:
    settings = get_settings()
    if not settings.bot_token or not settings.admin_id_list:
        return
    if monitor.paused:
        return

    brief = {}
    try:
        parsed = json.loads(order.match_reasons or "{}")
        if isinstance(parsed, dict) and (
            "client_need" in parsed or "reasons" in parsed
        ):
            brief = parsed
    except json.JSONDecodeError:
        brief = {"reasons_raw": order.match_reasons}

    need = html.escape(str(brief.get("client_need") or order.title)[:350])
    offer = html.escape(str(brief.get("my_offer") or "—")[:350])
    price = brief.get("price_rub") or "—"
    price_note = html.escape(str(brief.get("price_note") or "")[:160])
    intent = html.escape(str(brief.get("intent_title") or brief.get("intent") or ""))
    reasons = brief.get("reasons") or []
    reasons_s = html.escape(", ".join(str(r) for r in reasons[:6]))

    bot = Bot(token=settings.bot_token)
    text = (
        f"<b>На подтверждение</b> · <code>{html.escape(order.source)}</code> · "
        f"score <b>{order.match_score:.0f}</b>"
        f"{f' · {intent}' if intent else ''}\n\n"
        f"<b>Заказчик хочет:</b>\n{need}\n\n"
        f"<b>Могу дать:</b>\n{offer}\n\n"
        f"<b>Цена для отклика:</b> <b>{price}</b> ₽"
        f"{f' — {price_note}' if price_note else ''}\n\n"
        f"<b>{html.escape(order.title[:200])}</b>\n"
        f"<i>{reasons_s}</i>\n\n"
        f"<b>Черновик отклика:</b>\n{html.escape(draft_text[:2000])}\n\n"
        f"Подтвердите кнопками ниже или поправьте текст."
    )
    kb = _order_keyboard(order.id, order.url, order.source)
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(
                admin_id,
                text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Notify failed for %s", admin_id)

    monitor.mark_notify()
    async with async_session() as session:
        db_order = await session.get(Order, order.id)
        if db_order:
            db_order.status = OrderStatus.NOTIFIED
            pipeline = OrderPipeline(session)
            await pipeline.log_action(order.id, "notified", {})
            await session.commit()
    await bot.session.close()


async def _status_text() -> str:
    settings = get_settings()
    async with async_session() as session:
        from app.services.analytics import get_dashboard

        dash = await get_dashboard(session)

    hunting = monitor.status_label()
    lines = [
        f"<b>OrderHunter</b> — {hunting}",
        "",
        f"Пауза карточек: <b>{'да' if monitor.paused else 'нет'}</b>",
        f"Последний ingest: <b>{_fmt_dt(monitor.last_ingest_at)}</b>",
        f"Последняя карточка: <b>{_fmt_dt(monitor.last_notify_at)}</b>",
    ]
    if monitor.last_title:
        lines.append(
            f"Последний заказ: <code>{html.escape(monitor.last_source)}</code> — "
            f"{html.escape(monitor.last_title)}"
        )
    lines += [
        "",
        f"В очереди (черновики): <b>{dash['pending']}</b>",
        f"Сегодня: seen <b>{dash['today']['seen']}</b> · "
        f"matched <b>{dash['today']['matched']}</b> · "
        f"карточек <b>{dash['today']['notified']}</b> · "
        f"отправлено <b>{dash['today']['sent']}</b>",
        "",
        "Источники:",
        f"· Telegram MTProto: <b>вкл</b> (отдельный сервис)",
        f"· FL.ru: <b>{'вкл' if settings.fl_ru_enabled else 'выкл'}</b>",
        f"· Kwork: <b>{'вкл' if settings.kwork_enabled else 'выкл'}</b>",
        f"· LLM: <b>{'вкл' if settings.llm_enabled else 'выкл'}</b>",
        f"· Worker: <b>{'вкл' if settings.worker_enabled else 'выкл'}</b>",
    ]
    return "\n".join(lines)


async def _stats_text() -> str:
    from app.services.analytics import get_dashboard, get_funnel

    async with async_session() as session:
        dash = await get_dashboard(session)
        funnel = await get_funnel(session, days=7)

    t = dash["today"]
    lines = [
        "<b>Статистика</b>",
        "",
        "<b>Сегодня</b>",
        f"seen → matched → карточки → sent",
        f"<b>{t['seen']}</b> → <b>{t['matched']}</b> → "
        f"<b>{t['notified']}</b> → <b>{t['sent']}</b>",
        f"пропущено: <b>{t['skipped']}</b>",
        "",
        "<b>По источникам сегодня</b>",
    ]
    if dash["by_source_today"]:
        for src, cnt in sorted(dash["by_source_today"].items(), key=lambda x: -x[1]):
            lines.append(f"· <code>{html.escape(src)}</code>: {cnt}")
    else:
        lines.append("· пока пусто")

    lines += ["", "<b>Все статусы (всего)</b>"]
    if dash["by_status"]:
        for st, cnt in sorted(dash["by_status"].items(), key=lambda x: -x[1]):
            lines.append(f"· {html.escape(st)}: {cnt}")
    else:
        lines.append("· пока пусто")

    lines += ["", "<b>Воронка 7 дней</b>"]
    if funnel:
        for row in funnel:
            lines.append(
                f"{row['day']}: {row['seen']}→{row['matched']}→"
                f"{row['notified']}→{row['sent']}"
            )
    else:
        lines.append("· нет данных")
    return "\n".join(lines)


async def _queue_text() -> str:
    from app.services.analytics import get_dashboard

    async with async_session() as session:
        dash = await get_dashboard(session)
    lines = [f"<b>Очередь</b> — ждут действия: <b>{dash['pending']}</b>", ""]
    if not dash["queue"]:
        lines.append("Пусто. Когда найдётся заказ — придёт карточка.")
        return "\n".join(lines)
    for o in dash["queue"]:
        lines.append(
            f"· <code>{html.escape(o.source)}</code> "
            f"#{o.id} score {o.match_score:.0f} — "
            f"{html.escape(o.title[:80])}"
        )
    lines.append("\nКарточки уже в чате — кнопки под каждым заказом.")
    return "\n".join(lines)


def _sources_text() -> str:
    s = get_settings()
    return "\n".join(
        [
            "<b>Источники поиска</b>",
            "",
            f"{'🟢' if True else '⚪'} Telegram-каналы (mtproto-worker)",
            f"{'🟢' if s.fl_ru_enabled else '⚪'} FL.ru "
            f"(каждые {s.fl_ru_poll_interval_seconds}с)",
            f"{'🟢' if s.kwork_enabled else '⚪'} Kwork "
            f"(каждые {s.kwork_poll_interval_seconds}с)",
            "",
            f"LLM: {'🟢' if s.llm_enabled else '⚪'} {html.escape(s.llm_model)}",
            f"Worker API: {'🟢' if s.worker_enabled else '⚪'}",
            "",
            f"Режим сейчас: <b>{monitor.status_label()}</b>",
            "",
            "Вкл/выкл площадок — через Railway Variables "
            "(FL_RU_ENABLED / KWORK_ENABLED), затем redeploy.",
        ]
    )


def _help_text() -> str:
    return "\n".join(
        [
            "<b>Помощь</b>",
            "",
            "Кнопки <b>под строкой ввода</b>:",
            f"· {BTN_STATUS} — ищет или на паузе, последние события",
            f"· {BTN_STATS} — воронка и цифры",
            f"· {BTN_QUEUE} — заказы, ждущие вашего решения",
            f"· {BTN_SOURCES} — какие площадки включены",
            f"· {BTN_PAUSE} / {BTN_RESUME} — не слать карточки / снова искать",
            "",
            "На карточке заказа:",
            "· ✅ Отправить — отметить отправленным",
            "· 🚀 Kwork отклик — отправить через API",
            "· ✏️ Править — прислать новый текст одним сообщением",
            "· ⏭ Пропуск / 🔗 Открыть",
        ]
    )


@router.message(Command("start", "menu"))
async def cmd_start(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Доступ только для ADMIN_TELEGRAM_IDS.")
        return
    text = await _status_text()
    await message.answer(
        text + "\n\nМеню закреплено под строкой ввода.",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_help_text(), reply_markup=main_keyboard(), parse_mode="HTML")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    await message.answer(
        await _stats_text(), reply_markup=main_keyboard(), parse_mode="HTML"
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    await message.answer(
        await _status_text(), reply_markup=main_keyboard(), parse_mode="HTML"
    )


@router.message(F.text == BTN_STATUS)
async def btn_status(message: Message) -> None:
    await message.answer(
        await _status_text(), reply_markup=main_keyboard(), parse_mode="HTML"
    )


@router.message(F.text == BTN_STATS)
async def btn_stats(message: Message) -> None:
    await message.answer(
        await _stats_text(), reply_markup=main_keyboard(), parse_mode="HTML"
    )


@router.message(F.text == BTN_QUEUE)
async def btn_queue(message: Message) -> None:
    await message.answer(
        await _queue_text(), reply_markup=main_keyboard(), parse_mode="HTML"
    )


@router.message(F.text == BTN_SOURCES)
async def btn_sources(message: Message) -> None:
    await message.answer(
        _sources_text(), reply_markup=main_keyboard(), parse_mode="HTML"
    )


@router.message(F.text == BTN_HELP)
async def btn_help(message: Message) -> None:
    await message.answer(_help_text(), reply_markup=main_keyboard(), parse_mode="HTML")


@router.message(F.text == BTN_PAUSE)
async def btn_pause(message: Message) -> None:
    monitor.pause()
    await message.answer(
        "⏸ Поиск на паузе.\n"
        "Ingest идёт, но <b>новые карточки не приходят</b>.\n"
        f"Нажмите «{BTN_RESUME}», чтобы снова получать заказы.",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text == BTN_RESUME)
async def btn_resume(message: Message) -> None:
    monitor.resume()
    await message.answer(
        "▶️ Снова ищем заказы.\nПодходящие будут приходить карточками в этот чат.",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


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
    await query.message.answer(
        "Пришлите новый текст отклика одним сообщением.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text)
async def on_text(message: Message) -> None:
    # Menu buttons handled above; leftover text = draft edit or ignore.
    if not message.from_user:
        return
    order_id = _pending_edits.pop(message.from_user.id, None)
    if not order_id:
        await message.answer(
            "Выберите пункт меню под строкой ввода.",
            reply_markup=main_keyboard(),
        )
        return
    async with async_session() as session:
        draft = await session.scalar(
            select(Draft).where(Draft.order_id == order_id).order_by(Draft.id.desc())
        )
        if draft:
            draft.text = message.text or ""
            await session.commit()
    await message.answer(
        "Черновик обновлён. Нажмите «✅ Отправить» на карточке заказа.",
        reply_markup=main_keyboard(),
    )


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
        data = json.loads(order.raw_json or "{}")
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
