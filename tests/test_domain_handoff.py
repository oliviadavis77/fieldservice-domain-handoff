from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

from fieldservice.domain_onboarding import DomainOnboarding, DomainOnboardingRequest


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def add_domain(self, domain: str, onboarding_id: str) -> dict[str, Any]:
        self.calls.append(("add_domain", {"domain": domain}))
        return {"zone_id": "zone_field_42"}

    async def upsert_cname(
        self, zone_id: str, name: str, content: str, onboarding_id: str
    ) -> dict[str, Any]:
        self.calls.append(("upsert_cname", {"zone_id": zone_id, "name": name}))
        return {"record_id": "record_7"}

    async def register_webhook(
        self, url: str, secret: str, onboarding_id: str
    ) -> dict[str, Any]:
        self.calls.append(("register_webhook", {"url": url}))
        return {"id": "webhook_3"}

    async def verify_domain(self, domain: str) -> dict[str, Any]:
        self.calls.append(("verify_domain", {"domain": domain}))
        return {"status": "pending"}


def test_verified_domain_releases_dispatch_after_zone_record_write() -> None:
    gateway = RecordingGateway()
    flow = DomainOnboarding(gateway, "test-signing-secret")
    request = DomainOnboardingRequest.model_validate(
        {
            "domain": "repairs.customer.example",
            "cname_target": "tenant.product.example",
            "callback_url": "https://product.example/webhooks/infrai",
            "work_order": {
                "work_order_id": "wo-42",
                "photos": [{"object_key": "wo-42/panel.jpg", "caption": "Panel"}],
                "follow_up": {
                    "technician_id": "tech-8",
                    "note": "Send the finished gallery",
                    "due_at": "2026-09-15T11:30:00Z",
                },
            },
        }
    )

    pending = asyncio.run(flow.start(request))

    assert pending.dispatch_status == "domain_pending"
    assert gateway.calls[1] == (
        "upsert_cname",
        {"zone_id": "zone_field_42", "name": "repairs.customer.example"},
    )
    assert [name for name, _ in gateway.calls] == [
        "add_domain",
        "upsert_cname",
        "register_webhook",
        "verify_domain",
    ]

    body = json.dumps(
        {
            "event": "dns.domain.verified",
            "data": {"onboarding_id": "wo-42", "domain": request.domain},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(b"test-signing-secret", body, hashlib.sha256).hexdigest()

    released = flow.accept_verification(body, signature)

    assert released.dispatch_status == "dispatch_ready"
    assert released.photos[0].caption == "Panel"
    assert released.follow_up.technician_id == "tech-8"
