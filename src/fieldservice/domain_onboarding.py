from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field, HttpUrl


class WorkPhoto(BaseModel):
    object_key: str
    caption: str


class TechnicianFollowUp(BaseModel):
    technician_id: str
    note: str
    due_at: str


class WorkOrder(BaseModel):
    work_order_id: str
    dispatch_status: str = "domain_pending"
    photos: list[WorkPhoto] = Field(min_length=1)
    follow_up: TechnicianFollowUp


class DomainOnboardingRequest(BaseModel):
    domain: str
    cname_target: str
    callback_url: HttpUrl
    work_order: WorkOrder


class DomainOnboardingResult(BaseModel):
    onboarding_id: str
    domain: str
    zone_id: str
    dispatch_status: str
    photo_count: int
    verification: str


class VerificationEvent(BaseModel):
    event: str
    data: dict[str, Any]


class Gateway(Protocol):
    async def add_domain(self, domain: str, onboarding_id: str) -> dict[str, Any]:
        pass

    async def upsert_cname(
        self, zone_id: str, name: str, content: str, onboarding_id: str
    ) -> dict[str, Any]:
        pass

    async def register_webhook(
        self, url: str, secret: str, onboarding_id: str
    ) -> dict[str, Any]:
        pass

    async def verify_domain(self, domain: str) -> dict[str, Any]:
        pass


@dataclass(slots=True)
class OnboardingRecord:
    domain: str
    zone_id: str
    work_order: WorkOrder


class DomainOnboarding:
    def __init__(self, gateway: Gateway, webhook_secret: str) -> None:
        self.gateway = gateway
        self.webhook_secret = webhook_secret
        self.records: dict[str, OnboardingRecord] = {}

    async def start(self, request: DomainOnboardingRequest) -> DomainOnboardingResult:
        onboarding_id = request.work_order.work_order_id
        domain_data = await self.gateway.add_domain(request.domain, onboarding_id)
        zone_id = str(domain_data["zone_id"])
        await self.gateway.upsert_cname(
            zone_id, request.domain, request.cname_target, onboarding_id
        )
        await self.gateway.register_webhook(
            str(request.callback_url), self.webhook_secret, onboarding_id
        )
        await self.gateway.verify_domain(request.domain)
        self.records[onboarding_id] = OnboardingRecord(
            domain=request.domain,
            zone_id=zone_id,
            work_order=request.work_order,
        )
        return DomainOnboardingResult(
            onboarding_id=onboarding_id,
            domain=request.domain,
            zone_id=zone_id,
            dispatch_status=request.work_order.dispatch_status,
            photo_count=len(request.work_order.photos),
            verification="pending_webhook",
        )

    def accept_verification(self, body: bytes, signature: str) -> WorkOrder:
        expected = hmac.new(
            self.webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("invalid webhook signature")
        event = VerificationEvent.model_validate(json.loads(body))
        onboarding_id = str(event.data["onboarding_id"])
        record = self.records[onboarding_id]
        if event.event == "dns.domain.verified":
            record.work_order.dispatch_status = "dispatch_ready"
        return record.work_order
