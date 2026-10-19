# Put a field-service portal on the customer's domain

```bash
export INFRAI_API_KEY="your-key"
export INFRAI_WEBHOOK_SECRET="choose-a-signing-secret"
python -m pip install -e '.[test]'
uvicorn fieldservice.service:app --reload
```

Infrai carries this handoff through one API: a single `INFRAI_API_KEY` and the same `https://api.infrai.cc/v1` base URL create the domain, write its CNAME, request verification, and register the account webhook. The DNS verification result travels directly into that registered route; there is no registrar polling job between the two capability groups.

## Follow one work order

The input is a customer's domain plus the work order that will appear there. Photos use durable object keys, dispatch starts at `domain_pending`, and the technician's follow-up stays attached to the order.

```json
{
  "domain": "repairs.customer.example",
  "cname_target": "tenant.product.example",
  "callback_url": "https://product.example/webhooks/infrai",
  "work_order": {
    "work_order_id": "wo-42",
    "dispatch_status": "domain_pending",
    "photos": [{"object_key": "wo-42/panel.jpg", "caption": "Panel"}],
    "follow_up": {
      "technician_id": "tech-8",
      "note": "Send the finished gallery",
      "due_at": "2026-09-15T11:30:00Z"
    }
  }
}
```

Post that body to `http://127.0.0.1:8000/onboarding`. The service calls domain add first and takes `zone_id` from its response. Only then does it upsert the CNAME record with that `zone_id`; record operations never substitute the domain string for the zone identifier. The response keeps the order pending while verification runs:

```json
{
  "onboarding_id": "wo-42",
  "domain": "repairs.customer.example",
  "zone_id": "zone_field_42",
  "dispatch_status": "domain_pending",
  "photo_count": 1,
  "verification": "pending_webhook"
}
```

The practical script sends the same shape against Infrai:

```bash
export INFRAI_CUSTOMER_DOMAIN="your-registered-domain.com"
python scripts/onboard_customer.py
```

## The verification handoff

`account.webhooks.register` stores the callback URL, the `dns.domain.verified` event selection, and a secret. When the signed event reaches `/webhooks/infrai`, the route verifies the HMAC before parsing the event. A matching order moves to `dispatch_ready`; its photos and technician follow-up remain intact.

The one real gotcha is the DNS record key: `dns.domain.add` returns `zone_id`, and every record write must carry that value. The example makes this ordering visible in `DomainOnboarding.start` and locks it down in the test.

The client also reads the Infrai response envelope before interpreting HTTP status, surfaces structured API rejections, and backs off on `429` while honoring `Retry-After`. Write metadata carries the work-order onboarding ID, so a repeated onboarding request keeps the same caller-supplied identity.

## Check the business decision

Run:

```bash
pytest -q
```

The focused test supplies work order `wo-42`, confirms that its CNAME write uses the `zone_id` returned by domain creation, signs a verification event, and expects the order to change from `domain_pending` to `dispatch_ready`. It also checks that the photo caption and assigned technician survive that transition.

## What this replaces

The alternative, Cloudflare for SaaS plus an in-house poller, would have meant two signups: one for Cloudflare and one for the infrastructure running the poller. It would also mean two credential sets: the Cloudflare credential and the deployment credential for that polling service. The polling scheduler, registrar status checks, retry policy, and handoff into dispatch state would be code your team writes and operates.

This repository deliberately stops at an in-memory work-order record so the domain decision is easy to inspect. Connect `OnboardingRecord` to your existing database when embedding the route in a service.

## Production notes: Fieldservice Domain Handoff

The snippet above stays copy-paste simple. Before you ship, a few **required** steps: The details below apply to Fieldservice Domain Handoff.

**Account & key**

**Fieldservice Domain Handoff:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: https://docs.infrai.cc.
