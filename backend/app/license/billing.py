"""Stripe / hosted checkout stubs — NOT implemented in Phase 1.

Self-hosted DataMETL must never embed Stripe secret keys. Online purchase (Checkout +
webhooks that email a signed license) is a later batch. This module only reserves the
interface so callers can detect "not configured".
"""
from __future__ import annotations

from typing import Protocol


class BillingProvider(Protocol):
    def create_checkout_session(self, *, email: str, tier: str) -> str:
        """Return a hosted checkout URL. Phase 1: not implemented."""
        ...


class StripeCheckoutNotImplemented:
    """Placeholder — raises until a later Stripe batch."""

    def create_checkout_session(self, *, email: str, tier: str) -> str:
        raise NotImplementedError(
            "Stripe Checkout is not included in Phase 1. "
            "Issue an offline Pro license with scripts/issue_license.py instead."
        )


def get_billing_provider() -> BillingProvider:
    return StripeCheckoutNotImplemented()
