import hashlib
import logging
import time

import httpx

from app.config import get_settings
from app.connectors.base import BaseConnector
from app.core.normalizer import NormalizedOrder, normalize_kwork_project

logger = logging.getLogger(__name__)

KWORK_API = "https://api.kwork.ru"


class KworkConnector(BaseConnector):
    name = "kwork"

    def __init__(self):
        self.settings = get_settings()
        self._token: str | None = None
        self._token_expires = 0.0

    async def poll(self) -> list[NormalizedOrder]:
        if not self.settings.kwork_enabled:
            return []
        if not self.settings.kwork_login or not self.settings.kwork_password:
            return []

        orders: list[NormalizedOrder] = []
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{KWORK_API}/projects",
                    json={"token": token, "categories": [], "page": 1},
                )
                resp.raise_for_status()
                data = resp.json()
                projects = data.get("data", data.get("projects", []))
                if isinstance(projects, dict):
                    projects = projects.get("projects", [])
                for p in projects[:30]:
                    pid = p.get("id") or p.get("project_id")
                    if not pid:
                        continue
                    title = str(p.get("name") or p.get("title") or "")
                    desc = str(p.get("description") or title)
                    budget = str(p.get("priceLimit") or p.get("budget") or "")
                    url = f"https://kwork.ru/projects/{pid}"
                    orders.append(
                        normalize_kwork_project(int(pid), title, desc, url, budget)
                    )
        except Exception:
            logger.exception("Kwork poll failed")
        return orders

    async def submit_offer(self, project_id: int, text: str, price: int) -> dict:
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{KWORK_API}/offer/create",
                json={
                    "token": token,
                    "project_id": project_id,
                    "description": text,
                    "price": price,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires - 60:
            return self._token

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{KWORK_API}/signIn",
                json={
                    "login": self.settings.kwork_login,
                    "password": self.settings.kwork_password,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("response", data).get("token") or data.get("token")
            if not token:
                raise RuntimeError(f"Kwork auth failed: {data}")
            self._token = token
            self._token_expires = now + 3600
            return token

    @staticmethod
    def password_sign(password: str) -> str:
        return hashlib.md5(password.encode()).hexdigest()
