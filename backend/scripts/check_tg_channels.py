import re
import ssl
import urllib.request

ctx = ssl.create_default_context()
names = [
    "javascript_jobs",
    "nodejs_jobs",
    "golang_jobs",
    "uiux_jobs",
    "qa_jobs",
    "fordev",
    "workayte",
    "jobGeeks",
    "vakansii_it",
    "job_python",
    "jc_it",
    "jcit",
    "freelancetaverna",
    "it_zakazy",
    "zakazy_it",
    "zakazy_programmistam",
    "freelance_it",
    "itfreelance",
    "dev_freelance",
    "web_zakazy",
    "react_jobs",
    "vue_jobs",
    "typescript_jobs",
    "nextjs_jobs",
    "fastapi_jobs",
    "products_jobs",
    "devjobs_for_devs",
    "forwebdev",
    "progjob",
    "freelanceGeeks",
    "trudoteka",
    "udalennaya_rabota",
    "frilans_chat",
    "zakazy_frilans",
    "it_frilans",
    "web_frilans",
    "bots_jobs",
    "telegram_bots",
    "parser_jobs",
    "bitrix24_jobs",
    "amocrm_jobs",
    "crm_freelance",
    "weblancer_net",
    "hablance",
    "profi_ru",
    "youdo_com",
    "workzilla_com",
    "expertiza_ru",
    "fl_projects",
    "kwork_orders",
    "remote_it",
    "it_remote_jobs",
    "fullstack_jobs",
    "backend_vacancy",
    "frontend_vacancy",
    "php_vacancy",
    "python_vacancy",
    "dev_chat_ru",
    "coders_chat",
    "webdev_chat",
    "freelance_dev_ru",
    "orders_dev",
    "dev_orders_ru",
    "site_orders",
    "landing_orders",
    "bot_orders_ru",
    "tgbot_orders",
    "miniapp_jobs",
    "automation_ru",
    "n8n_ru",
    "integracii_jobs",
]

for n in names:
    try:
        req = urllib.request.Request(
            f"https://t.me/{n}", headers={"User-Agent": "Mozilla/5.0"}
        )
        html = urllib.request.urlopen(req, context=ctx, timeout=15).read().decode(
            "utf-8", "replace"
        )
        title_m = re.search(r'og:title" content="([^"]+)"', html)
        extra_m = re.search(r'tgme_page_extra">([^<]+)', html)
        title = title_m.group(1) if title_m else "?"
        extra = extra_m.group(1).strip() if extra_m else "NO_EXTRA"
        # private invite-only or missing
        if "tgme_page_title" not in html and "og:title" not in html:
            print(f"BAD\t{n}")
            continue
        print(f"OK\t{n}\t{extra}\t{title}")
    except Exception as e:
        print(f"ERR\t{n}\t{e}")
