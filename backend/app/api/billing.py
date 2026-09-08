"""Stripe webhook endpoint for vendor-side Pro license issuance.

Only registered / active when issuer env is present. Community self-hosted installs
never require Stripe secrets — this route returns 404 when disabled.
"""
from __future__ import annotations

import logging

import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.license.billing import handle_stripe_webhook, issuer_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> JSONResponse:
    """Receive Stripe events; mint + deliver a Pro ``dmtl1`` key on successful checkout.

    Disabled (404) unless ``STRIPE_SECRET_KEY`` and ``STRIPE_WEBHOOK_SECRET`` are set.
    """
    if not issuer_enabled():
        raise HTTPException(status_code=404, detail="Stripe webhook issuer is not enabled")

    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    payload = await request.body()
    try:
        result = handle_stripe_webhook(payload, stripe_signature)
    except stripe.SignatureVerificationError as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from e
    except ValueError as e:
        logger.warning("Stripe webhook payload error: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Always 200 for verified events (including ignored / replay) so Stripe does not retry forever.
    body = {
        "status": result.status,
        "event_id": result.event_id,
        "email": result.email,
        "session_id": result.session_id,
        "reason": result.reason,
        "delivered_via": result.delivered_via,
        # Return key for local stripe listen / test runs; production delivery is email + logs.
        "license_key": result.license_key,
    }
    return JSONResponse(body)
