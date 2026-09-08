"""Stripe webhook license issuer (Phase 2) — mocked construct_event / fixtures."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Env before app imports (conftest also sets these).
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.pop("DATAMETL_LICENSE_DEV_BYPASS", None)
# Ensure issuer disabled by default for import of main / other tests.
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)

from app.license.keys import generate_keypair_b64url
from app.license.token import verify_license

PRO_PRICE = "price_1UDWhFLRy9hgB11RWQ9Xp9FJ"


@pytest.fixture()
def signing_env(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    priv, pub = generate_keypair_b64url()
    monkeypatch.setenv("LICENSE_SIGNING_KEY", priv)
    monkeypatch.setenv("LICENSE_PUBLIC_KEY", pub)
    return priv, pub


@pytest.fixture()
def issuer_env(monkeypatch: pytest.MonkeyPatch, signing_env: tuple[str, str], tmp_path):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", PRO_PRICE)
    store = tmp_path / "issuance.json"
    monkeypatch.setenv("STRIPE_ISSUANCE_STORE_PATH", str(store))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    from app.license import billing as billing_mod

    billing_mod.reset_issuance_store_for_tests(str(store))
    return store


def _checkout_event(
    *,
    event_id: str = "evt_test_1",
    email: str = "buyer@example.com",
    session_id: str = "cs_test_1",
    price_id: str = PRO_PRICE,
    payment_status: str = "paid",
    status: str = "complete",
) -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "mode": "subscription",
                "payment_status": payment_status,
                "status": status,
                "customer_email": email,
                "customer_details": {"email": email},
                "line_items": {
                    "data": [{"price": {"id": price_id}}],
                },
            }
        },
    }


def test_issuer_disabled_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    from app.license.billing import issuer_enabled

    assert issuer_enabled() is False


def test_issuer_enabled_requires_both_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.license import billing as billing_mod

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    assert billing_mod.issuer_enabled() is False
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    assert billing_mod.issuer_enabled() is True


def test_process_checkout_mints_pro_license(issuer_env, signing_env) -> None:
    from app.license.billing import process_stripe_event

    result = process_stripe_event(_checkout_event())
    assert result.status == "issued"
    assert result.email == "buyer@example.com"
    assert result.license_key and result.license_key.startswith("dmtl1.")
    assert result.delivered_via == "log"
    payload = verify_license(result.license_key)
    assert payload.tier == "pro"
    assert payload.email == "buyer@example.com"


def test_idempotent_replay_same_event(issuer_env, signing_env) -> None:
    from app.license.billing import process_stripe_event

    first = process_stripe_event(_checkout_event(event_id="evt_replay"))
    second = process_stripe_event(_checkout_event(event_id="evt_replay"))
    assert first.status == "issued"
    assert second.status == "replay"
    assert second.license_key == first.license_key
    assert second.reason == "already_processed"


def test_idempotent_same_session_different_event(issuer_env, signing_env) -> None:
    from app.license.billing import process_stripe_event

    first = process_stripe_event(_checkout_event(event_id="evt_a", session_id="cs_same"))
    second = process_stripe_event(_checkout_event(event_id="evt_b", session_id="cs_same"))
    assert first.status == "issued"
    assert second.status == "replay"
    assert second.license_key == first.license_key
    assert second.reason == "session_already_issued"


def test_ignores_wrong_price(issuer_env, signing_env) -> None:
    from app.license.billing import process_stripe_event

    # Non-subscription object with wrong price and no mode=subscription fallback
    event = {
        "id": "evt_wrong",
        "type": "invoice.paid",
        "data": {
            "object": {
                "object": "invoice",
                "customer_email": "x@example.com",
                "lines": {"data": [{"price": {"id": "price_OTHER"}}]},
            }
        },
    }
    result = process_stripe_event(event)
    assert result.status == "ignored"
    assert result.reason == "price_mismatch_or_unpaid"


def test_invoice_paid_mints(issuer_env, signing_env) -> None:
    from app.license.billing import process_stripe_event

    event = {
        "id": "evt_inv",
        "type": "invoice.paid",
        "data": {
            "object": {
                "object": "invoice",
                "customer_email": "inv@example.com",
                "lines": {"data": [{"price": {"id": PRO_PRICE}}]},
            }
        },
    }
    result = process_stripe_event(event)
    assert result.status == "issued"
    assert result.email == "inv@example.com"


def test_unhandled_event_ignored(issuer_env, signing_env) -> None:
    from app.license.billing import process_stripe_event

    result = process_stripe_event({"id": "evt_ping", "type": "ping", "data": {"object": {}}})
    assert result.status == "ignored"
    assert "unhandled_event" in (result.reason or "")


def test_webhook_route_404_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    # Import app after env cleared — issuer_enabled reads os.environ at request time
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/billing/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})
    assert r.status_code == 404


def test_webhook_route_verifies_and_mints(issuer_env, signing_env, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.license import billing as billing_mod
    from app.main import app

    event = _checkout_event(event_id="evt_http")

    def fake_construct(payload: bytes, sig: str, secret: str):
        assert secret == "whsec_test_fake"
        assert sig == "sig_test"
        return event

    monkeypatch.setattr(
        "stripe.Webhook.construct_event",
        fake_construct,
    )
    # Also patch module-level helper path used inside handle_stripe_webhook
    monkeypatch.setattr(billing_mod, "_construct_event", lambda payload, sig: event)

    client = TestClient(app)
    r = client.post(
        "/api/billing/stripe/webhook",
        content=json.dumps(event).encode(),
        headers={"Stripe-Signature": "sig_test", "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "issued"
    assert body["license_key"].startswith("dmtl1.")
    assert body["email"] == "buyer@example.com"

    # Replay
    r2 = client.post(
        "/api/billing/stripe/webhook",
        content=json.dumps(event).encode(),
        headers={"Stripe-Signature": "sig_test"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "replay"
    assert r2.json()["license_key"] == body["license_key"]


def test_webhook_bad_signature_400(issuer_env, monkeypatch: pytest.MonkeyPatch) -> None:
    import stripe

    from app.license import billing as billing_mod
    from app.main import app

    def boom(payload: bytes, sig: str):
        raise stripe.SignatureVerificationError("bad sig", sig)

    monkeypatch.setattr(billing_mod, "_construct_event", boom)
    client = TestClient(app)
    r = client.post(
        "/api/billing/stripe/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "bad"},
    )
    assert r.status_code == 400
    assert "signature" in r.json()["detail"].lower()


def test_smtp_delivery_when_configured(issuer_env, signing_env, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.license.billing import deliver_license_key

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASS", "pass")
    monkeypatch.setenv("SMTP_FROM", "licenses@example.com")

    smtp_instance = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = smtp_instance
    smtp_cm.__exit__.return_value = False

    with patch("app.license.billing.smtplib.SMTP", return_value=smtp_cm) as smtp_cls:
        channel = deliver_license_key(email="buyer@example.com", license_key="dmtl1.test.key")
        assert channel == "smtp"
        smtp_cls.assert_called_once()
        smtp_instance.send_message.assert_called_once()


def test_get_billing_provider_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.license.billing import (
        StripeBillingProvider,
        StripeCheckoutNotConfigured,
        get_billing_provider,
    )

    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    assert isinstance(get_billing_provider(), StripeCheckoutNotConfigured)

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec")
    assert isinstance(get_billing_provider(), StripeBillingProvider)
