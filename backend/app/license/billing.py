"""Vendor-side Stripe webhook license issuer (Phase 2).

Self-hosted Community/Pro installs do **not** need Stripe secrets. Issuer mode is only
active when ``STRIPE_SECRET_KEY`` and ``STRIPE_WEBHOOK_SECRET`` are both set (plus
``LICENSE_SIGNING_KEY`` to mint keys). Customer Payment Links stay on Stripe-hosted
Checkout; this module verifies webhooks and emails/logs a signed ``dmtl1`` Pro key.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

from app.license.token import LicensePayload, issue_license

logger = logging.getLogger(__name__)

# Events we mint a Pro license for (when price matches STRIPE_PRO_PRICE_ID).
_HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "invoice.paid",
        "customer.subscription.created",
    }
)


@dataclass(frozen=True)
class IssuanceResult:
    """Outcome of handling a Stripe billing event (returned to tests / webhook response)."""

    status: str  # issued | replay | ignored | error
    event_id: str
    email: str | None = None
    license_key: str | None = None
    session_id: str | None = None
    reason: str | None = None
    delivered_via: str | None = None  # smtp | log


class BillingProvider(Protocol):
    def create_checkout_session(self, *, email: str, tier: str) -> str:
        """Return a hosted checkout URL (Payment Link or Checkout Session)."""
        ...

    def handle_webhook(self, payload: bytes, signature_header: str) -> IssuanceResult:
        """Verify Stripe-Signature and process a mintable event."""
        ...


def issuer_enabled() -> bool:
    """True only when both Stripe secrets are configured (vendor issuer mode)."""
    secret = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    whsec = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    return bool(secret and whsec)


def payment_link_url() -> str | None:
    """Optional public Payment Link (also exposed to frontend via NEXT_PUBLIC_DATAMETL_PRO_URL)."""
    url = (os.environ.get("NEXT_PUBLIC_DATAMETL_PRO_URL") or "").strip()
    return url or None


def pro_price_id() -> str:
    return (os.environ.get("STRIPE_PRO_PRICE_ID") or "").strip()


class _IssuanceStore:
    """Lightweight idempotency by Stripe event id (and optional session id).

    File-backed JSON when ``STRIPE_ISSUANCE_STORE_PATH`` is set; otherwise in-memory
    (fine for tests / single-process issuer).
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._by_event: dict[str, dict[str, Any]] = {}
        self._by_session: dict[str, str] = {}  # session_id -> event_id
        if self._path and self._path.is_file():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._by_event = dict(raw.get("by_event") or {})
                self._by_session = dict(raw.get("by_session") or {})
            except Exception:
                logger.exception("Failed to load issuance store from %s", self._path)

    def get_by_event(self, event_id: str) -> IssuanceResult | None:
        with self._lock:
            data = self._by_event.get(event_id)
            if not data:
                return None
            return IssuanceResult(**data)

    def get_by_session(self, session_id: str) -> IssuanceResult | None:
        with self._lock:
            eid = self._by_session.get(session_id)
            if not eid:
                return None
            data = self._by_event.get(eid)
            if not data:
                return None
            return IssuanceResult(**data)

    def put(self, result: IssuanceResult) -> None:
        with self._lock:
            payload = asdict(result)
            self._by_event[result.event_id] = payload
            if result.session_id:
                self._by_session[result.session_id] = result.event_id
            if self._path:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(
                    json.dumps(
                        {"by_event": self._by_event, "by_session": self._by_session},
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )


_store: _IssuanceStore | None = None
_store_lock = threading.Lock()


def get_issuance_store() -> _IssuanceStore:
    global _store
    with _store_lock:
        if _store is None:
            path = (os.environ.get("STRIPE_ISSUANCE_STORE_PATH") or "").strip() or None
            _store = _IssuanceStore(path)
        return _store


def reset_issuance_store_for_tests(path: str | None = None) -> _IssuanceStore:
    """Replace the process-wide store (tests only)."""
    global _store
    with _store_lock:
        _store = _IssuanceStore(path)
        return _store


def _construct_event(payload: bytes, signature_header: str) -> Any:
    import stripe

    whsec = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    return stripe.Webhook.construct_event(payload, signature_header, whsec)


def _price_ids_from_obj(obj: dict[str, Any]) -> set[str]:
    """Best-effort extract Stripe Price ids from checkout / invoice / subscription objects."""
    found: set[str] = set()

    def _add(price: Any) -> None:
        if isinstance(price, str) and price.startswith("price_"):
            found.add(price)
        elif isinstance(price, dict):
            pid = price.get("id")
            if isinstance(pid, str) and pid.startswith("price_"):
                found.add(pid)

    meta = obj.get("metadata") or {}
    if isinstance(meta, dict):
        for key in ("price_id", "stripe_price_id", "STRIPE_PRO_PRICE_ID"):
            _add(meta.get(key))

    # checkout.session line_items (expanded) or display_items
    line_items = obj.get("line_items")
    if isinstance(line_items, dict):
        for item in line_items.get("data") or []:
            if isinstance(item, dict):
                _add(item.get("price"))
    elif isinstance(line_items, list):
        for item in line_items:
            if isinstance(item, dict):
                _add(item.get("price"))

    for item in obj.get("display_items") or []:
        if isinstance(item, dict):
            _add(item.get("price"))
            plan = item.get("plan")
            if isinstance(plan, dict):
                _add(plan.get("id"))

    # invoice.lines
    lines = obj.get("lines")
    if isinstance(lines, dict):
        for item in lines.get("data") or []:
            if isinstance(item, dict):
                _add(item.get("price"))
                _add(item.get("plan"))

    # subscription.items
    items = obj.get("items")
    if isinstance(items, dict):
        for item in items.get("data") or []:
            if isinstance(item, dict):
                _add(item.get("price"))
                _add(item.get("plan"))

    return found


def _matches_pro_price(obj: dict[str, Any]) -> bool:
    expected = pro_price_id()
    if not expected:
        # No filter configured — accept any mintable event object.
        return True
    prices = _price_ids_from_obj(obj)
    if prices:
        return expected in prices
    # Payment Link checkout.session.completed often omits line_items unless expanded.
    # Accept subscription-mode checkouts when we cannot see prices (caller may refine).
    mode = obj.get("mode")
    if mode == "subscription":
        return True
    # invoice / subscription without parseable prices: reject when filter is set
    if obj.get("object") in ("invoice", "subscription"):
        return False
    # Unknown object shape with filter set and no prices → reject
    return False


def _email_from_checkout_session(session: dict[str, Any]) -> str | None:
    details = session.get("customer_details") or {}
    if isinstance(details, dict):
        email = (details.get("email") or "").strip()
        if email:
            return email
    for key in ("customer_email", "customer"):
        val = session.get(key)
        if isinstance(val, str) and "@" in val:
            return val.strip()
    return None


def _email_from_invoice(invoice: dict[str, Any]) -> str | None:
    for key in ("customer_email", "receipt_email"):
        val = invoice.get(key)
        if isinstance(val, str) and "@" in val:
            return val.strip()
    details = invoice.get("customer_details") or {}
    if isinstance(details, dict):
        email = (details.get("email") or "").strip()
        if email:
            return email
    return None


def _email_from_subscription(sub: dict[str, Any]) -> str | None:
    meta = sub.get("metadata") or {}
    if isinstance(meta, dict):
        email = (meta.get("email") or "").strip()
        if email:
            return email
    # customer may be an expanded object
    customer = sub.get("customer")
    if isinstance(customer, dict):
        email = (customer.get("email") or "").strip()
        if email:
            return email
    return None


def _extract_mint_context(event_type: str, data_object: dict[str, Any]) -> tuple[str | None, str | None, bool]:
    """Return (email, session_id, price_ok)."""
    if event_type == "checkout.session.completed":
        email = _email_from_checkout_session(data_object)
        session_id = data_object.get("id") if isinstance(data_object.get("id"), str) else None
        # Prefer paid / complete sessions
        payment_status = data_object.get("payment_status")
        status = data_object.get("status")
        if payment_status and payment_status not in ("paid", "no_payment_required"):
            return email, session_id, False
        if status and status != "complete":
            return email, session_id, False
        return email, session_id, _matches_pro_price(data_object)

    if event_type == "invoice.paid":
        email = _email_from_invoice(data_object)
        session_id = None
        # Skip $0 / draft-like; invoice.paid is already paid
        return email, session_id, _matches_pro_price(data_object)

    if event_type == "customer.subscription.created":
        email = _email_from_subscription(data_object)
        session_id = None
        return email, session_id, _matches_pro_price(data_object)

    return None, None, False


def deliver_license_key(*, email: str, license_key: str) -> str:
    """Email the key when SMTP_* is configured; always log. Returns delivery channel."""
    # Never log the full key in production noise — include a short prefix for correlation.
    prefix = license_key[:18] + "…" if len(license_key) > 18 else license_key
    logger.info(
        "DataMETL Pro license issued for %s (key prefix %s). Full key follows for issuer ops.",
        email,
        prefix,
    )
    # Always emit the full key on a dedicated line so local stripe listen / test runs can copy it.
    logger.info("DATAMETL_LICENSE_KEY email=%s key=%s", email, license_key)

    host = (os.environ.get("SMTP_HOST") or "").strip()
    if not host:
        logger.info("SMTP_HOST not set — license delivery is log-only (no email sent).")
        return "log"

    port = int((os.environ.get("SMTP_PORT") or "587").strip() or "587")
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = (os.environ.get("SMTP_PASS") or os.environ.get("SMTP_PASSWORD") or "").strip()
    from_addr = (os.environ.get("SMTP_FROM") or user or "noreply@datametl.local").strip()

    msg = EmailMessage()
    msg["Subject"] = "Your DataMETL Pro license key"
    msg["From"] = from_addr
    msg["To"] = email
    msg.set_content(
        "Thank you for subscribing to DataMETL Pro.\n\n"
        "Activate this license key in Settings → License:\n\n"
        f"{license_key}\n\n"
        "Keep this key private. If you did not purchase DataMETL, ignore this email.\n"
    )

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls()
                smtp.ehlo()
            except smtplib.SMTPException:
                pass
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        logger.info("License email sent to %s via SMTP %s", email, host)
        return "smtp"
    except Exception:
        logger.exception("SMTP delivery failed for %s — key remains in logs above", email)
        return "log"


def mint_pro_license(*, email: str) -> str:
    """Sign a perpetual Pro dmtl1 key for the customer email."""
    payload = LicensePayload(
        tier="pro",
        issued_at=datetime.now(UTC),
        expires_at=None,
        email=email,
    )
    return issue_license(payload)


def process_stripe_event(event: dict[str, Any] | Any) -> IssuanceResult:
    """Core handler: idempotent mint + deliver for Pro subscription events."""
    if not isinstance(event, dict):
        # stripe.Event-like
        event = {
            "id": getattr(event, "id", None),
            "type": getattr(event, "type", None),
            "data": getattr(event, "data", None),
        }

    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    store = get_issuance_store()

    if event_id:
        prior = store.get_by_event(event_id)
        if prior is not None:
            logger.info("Stripe event %s already processed (%s) — idempotent replay", event_id, prior.status)
            return IssuanceResult(
                status="replay",
                event_id=event_id,
                email=prior.email,
                license_key=prior.license_key,
                session_id=prior.session_id,
                reason="already_processed",
                delivered_via=prior.delivered_via,
            )

    if event_type not in _HANDLED_EVENTS:
        return IssuanceResult(
            status="ignored",
            event_id=event_id or "unknown",
            reason=f"unhandled_event:{event_type}",
        )

    data = event.get("data") or {}
    obj = data.get("object") if isinstance(data, dict) else None
    if not isinstance(obj, dict):
        # stripe Event data.object may be a StripeObject
        if obj is not None and hasattr(obj, "to_dict"):
            obj = obj.to_dict()
        else:
            return IssuanceResult(
                status="ignored",
                event_id=event_id or "unknown",
                reason="missing_data_object",
            )

    email, session_id, price_ok = _extract_mint_context(event_type, obj)

    if session_id:
        prior_sess = store.get_by_session(session_id)
        if prior_sess is not None and prior_sess.status in ("issued", "replay"):
            # Same checkout session, different event id — do not double-mint.
            result = IssuanceResult(
                status="replay",
                event_id=event_id or prior_sess.event_id,
                email=prior_sess.email,
                license_key=prior_sess.license_key,
                session_id=session_id,
                reason="session_already_issued",
                delivered_via=prior_sess.delivered_via,
            )
            if event_id:
                store.put(result)
            return result

    if not price_ok:
        return IssuanceResult(
            status="ignored",
            event_id=event_id or "unknown",
            email=email,
            session_id=session_id,
            reason="price_mismatch_or_unpaid",
        )

    if not email:
        return IssuanceResult(
            status="ignored",
            event_id=event_id or "unknown",
            session_id=session_id,
            reason="missing_customer_email",
        )

    try:
        license_key = mint_pro_license(email=email)
    except Exception as e:
        logger.exception("Failed to mint license for %s", email)
        return IssuanceResult(
            status="error",
            event_id=event_id or "unknown",
            email=email,
            session_id=session_id,
            reason=f"mint_failed:{e}",
        )

    channel = deliver_license_key(email=email, license_key=license_key)
    result = IssuanceResult(
        status="issued",
        event_id=event_id or "unknown",
        email=email,
        license_key=license_key,
        session_id=session_id,
        delivered_via=channel,
    )
    if event_id:
        store.put(result)
    return result


def handle_stripe_webhook(payload: bytes, signature_header: str) -> IssuanceResult:
    """Verify signature then process. Raises ValueError / SignatureVerificationError."""
    import stripe

    try:
        event = _construct_event(payload, signature_header)
    except stripe.SignatureVerificationError:
        raise
    except Exception as e:
        raise ValueError(f"Invalid Stripe webhook payload: {e}") from e

    if hasattr(event, "to_dict"):
        event_dict = event.to_dict()
    elif isinstance(event, dict):
        event_dict = event
    else:
        event_dict = dict(event)
    return process_stripe_event(event_dict)


class StripeBillingProvider:
    """BillingProvider backed by Stripe Payment Link + webhook issuer."""

    def create_checkout_session(self, *, email: str, tier: str) -> str:
        """Prefer the configured Payment Link; Checkout Session API is optional later."""
        url = payment_link_url()
        if url:
            # Payment Links are static; email is collected on Stripe's hosted page.
            _ = (email, tier)
            return url
        raise NotImplementedError(
            "No NEXT_PUBLIC_DATAMETL_PRO_URL / Payment Link configured. "
            "Set the public Payment Link URL or issue an offline key with "
            "scripts/issue_license.py."
        )

    def handle_webhook(self, payload: bytes, signature_header: str) -> IssuanceResult:
        return handle_stripe_webhook(payload, signature_header)


class StripeCheckoutNotConfigured:
    """Used when issuer env is absent — Checkout URL + webhook both unavailable."""

    def create_checkout_session(self, *, email: str, tier: str) -> str:
        raise NotImplementedError(
            "Stripe issuer is not configured on this install. "
            "Issue an offline Pro license with scripts/issue_license.py, "
            "or enable vendor issuer mode (STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET)."
        )

    def handle_webhook(self, payload: bytes, signature_header: str) -> IssuanceResult:
        raise NotImplementedError("Stripe webhook issuer is disabled (missing STRIPE_* secrets).")


def get_billing_provider() -> BillingProvider:
    if issuer_enabled():
        return StripeBillingProvider()
    return StripeCheckoutNotConfigured()
