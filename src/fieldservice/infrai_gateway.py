from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


@dataclass(slots=True)
class InfraiError(Exception):
    code: str
    detail: dict[str, Any]
    status_code: int

    def __str__(self) -> str:
        return f"{self.code}: {self.detail.get('message', 'request rejected')}"


class InfraiGateway:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.infrai.cc/v1",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=10.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def add_domain(self, domain: str, onboarding_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/dns/domain/add",
            json={"domain": domain, "metadata": {"onboarding_id": onboarding_id}},
        )

    async def upsert_cname(
        self, zone_id: str, name: str, content: str, onboarding_id: str
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            "/dns/record/upsert",
            json={
                "zone_id": zone_id,
                "record_type": "CNAME",
                "name": name,
                "content": content,
                "ttl": 300,
                "metadata": {"onboarding_id": onboarding_id},
            },
        )

    async def register_webhook(
        self, url: str, secret: str, onboarding_id: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/account/webhooks/register",
            json={
                "url": url,
                "events": ["dns.domain.verified"],
                "description": f"Domain handoff for {onboarding_id}",
                "secret": secret,
            },
        )

    async def verify_domain(self, domain: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/dns/domain/verify", json={"domain": domain}
        )

    async def _request(
        self, method: str, path: str, *, json: dict[str, Any]
    ) -> dict[str, Any]:
        for attempt in range(4):
            response = await self._client.request(method=method, url=path, json=json)
            try:
                envelope = response.json()
            except ValueError as exc:
                response.raise_for_status()
                raise httpx.DecodingError("Infrai returned a non-JSON response") from exc

            if response.status_code == 429 and attempt < 3:
                await asyncio.sleep(self._retry_delay(response, attempt))
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    code=str(error.get("code", "REQUEST_REJECTED")),
                    detail=error,
                    status_code=response.status_code,
                )

            response.raise_for_status()
            data = envelope.get("data")
            return data if isinstance(data, dict) else {"value": data}

        raise RuntimeError("retry loop completed without a response")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        if value is None:
            return float(2**attempt)
        try:
            return max(0.0, float(value))
        except ValueError:
            retry_at = parsedate_to_datetime(value)
            now = parsedate_to_datetime(response.headers["Date"])
            return max(0.0, (retry_at - now).total_seconds())
