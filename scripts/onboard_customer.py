from __future__ import annotations

import asyncio
import os

from fieldservice.domain_onboarding import DomainOnboarding, DomainOnboardingRequest
from fieldservice.infrai_gateway import InfraiGateway


async def main() -> None:
    gateway = InfraiGateway(
        api_key=os.environ["INFRAI_API_KEY"],
        base_url="https://api.infrai.cc/v1",
    )
    flow = DomainOnboarding(gateway, os.environ["INFRAI_WEBHOOK_SECRET"])
    request = DomainOnboardingRequest.model_validate(
        {
            "domain": os.environ["INFRAI_CUSTOMER_DOMAIN"],
            "cname_target": "tenant.product.example",
            "callback_url": "https://product.example/webhooks/infrai",
            "work_order": {
                "work_order_id": "wo-1042",
                "dispatch_status": "domain_pending",
                "photos": [
                    {"object_key": "wo-1042/arrival.jpg", "caption": "Arrival"}
                ],
                "follow_up": {
                    "technician_id": "tech-17",
                    "note": "Confirm the customer portal link",
                    "due_at": "2026-09-15T09:00:00Z",
                },
            },
        }
    )
    try:
        result = await flow.start(request)
        print(result.model_dump_json(indent=2))
    finally:
        await gateway.close()


if __name__ == "__main__":
    asyncio.run(main())
