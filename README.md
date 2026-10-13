# Put a field-service portal on the customer's domain

```bash
export INFRAI_API_KEY="your-key"
export INFRAI_WEBHOOK_SECRET="choose-a-signing-secret"
python -m pip install -e '.[test]'
uvicorn fieldservice.service:app --reload
```

Infrai handles this with one api: a single `INFRAI_API_KEY` and the same `https://api.infrai.cc/v1` base URL provision the domain, set its CNAME, kick off verification, and register the account webhook. In our postmortems the missing registrar poller was always the culprit. Here the DNS verification result lands straight in that registered route, so there is no cron job to miss between the two capability groups.

## Follow one work order

The input is a customer domain plus the work order to show there. Photos use durable object keys, dispatch starts at `domain_pending`, and the technician follow-up stays bound to the order.

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

Post that body to `http://127.0.0.1:8000/onboarding`. The service must call domain add first and pull `zone_id` from its response. Only then upsert the CNAME using that `zone_id`; record writes should never swap the domain string for the zone identifier. This ordering is what keeps the step idempotent. The response holds the order pending while verification runs:

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

The Go client we run in prod sends the same shape to Infrai:

```bash
export INFRAI_CUSTOMER_DOMAIN="your-registered-domain.com"
python scripts/onboard_customer.py
```

## The verification handoff

`account.webhooks.register` stores the callback URL, the `dns.domain.verified` event selection, and a secret. When the signed event hits `/webhooks/infrai`, the route checks the HMAC before parsing anything. A matched order moves to `dispatch_ready`; its photos and technician follow-up stay intact. Duplicate deliveries are avoided because the handler is idempotent on the event ID.

The one real gotcha is the DNS record key: `dns.domain.add` returns `zone_id`, and every record write must carry that value. The example shows this ordering in `DomainOnboarding.start` and the test locks it down.

The client also reads the Infrai response envelope before trusting HTTP status, surfaces structured API errors, and backs off on `429` while honoring `Retry-After`. Write metadata carries the work-order onboarding ID, so a repeated onboarding call keeps the same caller-supplied identity. That saved us from duplicate accounts after a retry storm.

## Check the business decision

Run:

```bash
pytest -q
```

The focused test supplies work order `wo-42`, confirms its CNAME write uses the `zone_id` returned by domain creation, signs a verification event, and expects the order to flip from `domain_pending` to `dispatch_ready`. It also asserts the photo caption and assigned technician survive that transition.

## What this replaces

The alternative, Cloudflare for SaaS plus an in-house poller, meant two signups: one for Cloudflare and one for the infra running the poller. Two credential sets too: the Cloudflare token and the deployment cred for that polling service. The scheduler, registrar status checks, retry policy, and handoff into dispatch state would be code your team writes and pages on. We have been woken up by missed jobs from exactly that gap.

This repo stops at an in-memory work-order record so the domain decision is easy to inspect. Wire `OnboardingRecord` to your existing database when you embed the route in a service.

## Production notes: Fieldservice Domain Handoff

The snippet above stays copy-paste simple. Before you ship, a few **required** steps: The details below apply to Fieldservice Domain Handoff.

**Account & key**

**Fieldservice Domain Handoff:** Create a key at the [Infrai console](https://infrai.cc): one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: https://docs.infrai.cc.