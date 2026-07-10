"""Kwork connector via unofficial mobile API (api.kwork.ru)."""

from __future__ import annotations

import base64
import logging
import time

import httpx

from app.config import get_settings
from app.connectors.base import BaseConnector
from app.core.normalizer import NormalizedOrder, normalize_kwork_project

logger = logging.getLogger(__name__)

KWORK_API = "https://api.kwork.ru"
# Public credentials of the Kwork mobile client (same as pykwork / community libs).
_MOBILE_BASIC = base64.b64encode(b"mobile_api:qFvfRl7w").decode()


class KworkConnector(BaseConnector):
    name = "kwork"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._token: str | None = None
        self._token_expires = 0.0
        self._seen: set[str] = set()
        self._baselined = False

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "User-Agent": "OrderHunter/0.1",
            "Authorization": f"Basic {_MOBILE_BASIC}",
        }

    async def poll(self) -> list[NormalizedOrder]:
        if not self.settings.kwork_enabled:
            return []
        if not self.settings.kwork_login or not self.settings.kwork_password:
            logger.warning("Kwork enabled but KWORK_LOGIN/PASSWORD empty")
            return []

        orders: list[NormalizedOrder] = []
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{KWORK_API}/projects",
                    headers=self._headers(),
                    params={
                        "token": token,
                        "page": 1,
                        "categories": "",
                        "query": "",
                        "uad": "orderhunter",
                        "device": "orderhunter",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("success", True) and data.get("error"):
                    raise RuntimeError(f"Kwork projects error: {data.get('error')}")

                projects = self._extract_projects(data)
                for p in projects[:30]:
                    pid = p.get("id") or p.get("project_id")
                    if not pid:
                        continue
                    pid_s = str(pid)
                    if pid_s in self._seen:
                        continue
                    self._seen.add(pid_s)
                    if not self._baselined:
                        continue
                    title = str(p.get("name") or p.get("title") or "")
                    desc = str(p.get("description") or title)
                    budget = str(
                        p.get("priceLimit")
                        or p.get("budget")
                        or p.get("price")
                        or ""
                    )
                    url = f"https://kwork.ru/projects/{pid}"
                    orders.append(
                        normalize_kwork_project(int(pid), title, desc, url, budget)
                    )
                if not self._baselined:
                    self._baselined = True
                    logger.info("Kwork baseline done (%s projects marked seen)", len(self._seen))
        except Exception:
            logger.exception("Kwork poll failed")
        return orders

    async def submit_offer(self, project_id: int, text: str, price: int) -> dict:
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{KWORK_API}/offer",
                headers=self._headers(),
                params={
                    "token": token,
                    "project_id": project_id,
                    "description": text,
                    "price": price,
                    "uad": "orderhunter",
                    "device": "orderhunter",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("success") is False:
                raise RuntimeError(data.get("error") or str(data))
            return data

    async def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires - 60:
            return self._token

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{KWORK_API}/signIn",
                headers=self._headers(),
                params={
                    "login": self.settings.kwork_login,
                    "password": self.settings.kwork_password,
                    "uad": "orderhunter",
                    "device": "orderhunter",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise RuntimeError(f"Kwork auth failed: {data.get('error') or data}")
            token = (data.get("response") or {}).get("token") or data.get("token")
            if not token:
                raise RuntimeError(f"Kwork auth: no token in response: {data}")
            self._token = token
            self._token_expires = now + 3600
            logger.info("Kwork auth ok")
            return token

    @staticmethod
    def _extract_projects(data: dict) -> list[dict]:
        payload = data.get("response", data.get("data", data))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("projects", "wants", "list", "items"):
                val = payload.get(key)
                if isinstance(val, list):
                    return val
                if isinstance(val, dict) and isinstance(val.get("data"), list):
                    return val["data"]
        return []
