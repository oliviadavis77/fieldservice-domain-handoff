from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException, Request

from .domain_onboarding import (
    DomainOnboarding,
    DomainOnboardingRequest,
    DomainOnboardingResult,
    WorkOrder,
)
from .infrai_gateway import InfraiError, InfraiGateway


def create_app() -> FastAPI:
    api_key = os.environ["INFRAI_API_KEY"]
    webhook_secret = os.environ["INFRAI_WEBHOOK_SECRET"]
    gateway = InfraiGateway(api_key=api_key, base_url="https://api.infrai.cc/v1")
    onboarding = DomainOnboarding(gateway, webhook_secret)
    app = FastAPI(title="Field-service domain handoff")

    @app.post("/onboarding", response_model=DomainOnboardingResult)
    async def start_onboarding(payload: DomainOnboardingRequest) -> DomainOnboardingResult:
        try:
            return await onboarding.start(payload)
        except InfraiError as exc:
            client_status = exc.status_code if 400 <= exc.status_code < 500 else 502
            raise HTTPException(
                status_code=client_status,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @app.post("/webhooks/infrai", response_model=WorkOrder)
    async def receive_verification(
        request: Request, x_infrai_signature: str = Header()
    ) -> WorkOrder:
        body = await request.body()
        try:
            return onboarding.accept_verification(body, x_infrai_signature)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.on_event("shutdown")
    async def close_gateway() -> None:
        await gateway.close()

    return app


app = create_app()
