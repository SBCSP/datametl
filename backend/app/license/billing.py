"""Vendor-side Stripe webhook license issuer (Phase 2).

Self-hosted Community/Pro installs do **not** need Stripe secrets. Issuer mode is only
active when ``STRIPE_SECRET_KEY`` and ``STRIPE_WEBHOOK_SECRET`` are both set (plus
``LICENSE_SIGNING_KEY`` to mint keys). Customer Payment Links stay on Stripe-hosted
Checkout; this module verifies webhooks and emails/logs a signed ``dmtl1`` Pro key
bound to the subscription ``current_period_end`` (refreshed on ``invoice.paid``;
no renew after cancel).
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
    """Best-effort extract Stripe Price ids from checkout / invoice / subscription objects.

    Newer Invoice line items expose the price under ``pricing.price_details.price``
    (string id or expanded object) rather than top-level ``price`` / ``plan``.
    """
    found: set[str] = set()

    def _add(price: Any) -> None:
        if isinstance(price, str) and price.startswith("price_"):
            found.add(price)
        elif isinstance(price, dict):
            pid = price.get("id")
            if isinstance(pid, str) and pid.startswith("price_"):
                found.add(pid)

    def _add_from_line_item(item: dict[str, Any]) -> None:
        _add(item.get("price"))
        _add(item.get("plan"))
        pricing = item.get("pricing")
        if isinstance(pricing, dict):
            details = pricing.get("price_details")
            if isinstance(details, dict):
                _add(details.get("price"))
            _add(pricing.get("price"))

    meta = obj.get("metadata") or {}
    if isinstance(meta, dict):
        for key in ("price_id", "stripe_price_id", "STRIPE_PRO_PRICE_ID"):
            _add(meta.get(key))

    # checkout.session line_items (expanded) or display_items
    line_items = obj.get("line_items")
    if isinstance(line_items, dict):
        for item in line_items.get("data") or []:
            if isinstance(item, dict):
                _add_from_line_item(item)
    elif isinstance(line_items, list):
        for item in line_items:
            if isinstance(item, dict):
                _add_from_line_item(item)

    for item in obj.get("display_items") or []:
        if isinstance(item, dict):
            _add_from_line_item(item)
            plan = item.get("plan")
            if isinstance(plan, dict):
                _add(plan.get("id"))

    # invoice.lines
    lines = obj.get("lines")
    if isinstance(lines, dict):
        for item in lines.get("data") or []:
            if isinstance(item, dict):
                _add_from_line_item(item)
    elif isinstance(lines, list):
        for item in lines:
            if isinstance(item, dict):
                _add_from_line_item(item)

    # subscription.items
    items = obj.get("items")
    if isinstance(items, dict):
        for item in items.get("data") or []:
            if isinstance(item, dict):
                _add_from_line_item(item)
    elif isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                _add_from_line_item(item)

    # Recurse into expanded nested subscription (checkout / invoice).
    nested = _nested_subscription(obj)
    if nested is not None and nested is not obj:
        found |= _price_ids_from_obj(nested)

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


def _ts_to_utc(value: Any) -> datetime | None:
    """Convert a Stripe unix timestamp (or datetime) to timezone-aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=UTC)
    return None


def _nested_subscription(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Return an expanded subscription dict nested on checkout / invoice objects."""
    sub = obj.get("subscription")
    if isinstance(sub, dict):
        return sub
    parent = obj.get("parent")
    if isinstance(parent, dict):
        details = parent.get("subscription_details")
        if isinstance(details, dict):
            nested = details.get("subscription")
            if isinstance(nested, dict):
                return nested
    return None


def _subscription_id_from_obj(obj: dict[str, Any]) -> str | None:
    """Return a Stripe subscription id string when present (top-level or nested)."""
    sub = obj.get("subscription")
    if isinstance(sub, str) and sub.startswith("sub_"):
        return sub
    if isinstance(sub, dict):
        sid = sub.get("id")
        if isinstance(sid, str) and sid.startswith("sub_"):
            return sid
    parent = obj.get("parent")
    if isinstance(parent, dict):
        details = parent.get("subscription_details")
        if isinstance(details, dict):
            nested = details.get("subscription")
            if isinstance(nested, str) and nested.startswith("sub_"):
                return nested
            if isinstance(nested, dict):
                sid = nested.get("id")
                if isinstance(sid, str) and sid.startswith("sub_"):
                    return sid
    if obj.get("object") == "subscription":
        sid = obj.get("id")
        if isinstance(sid, str) and sid.startswith("sub_"):
            return sid
    return None


def _customer_id_from_obj(obj: dict[str, Any]) -> str | None:
    """Return a Stripe customer id when ``customer`` is a string (or nested)."""
    customer = obj.get("customer")
    if isinstance(customer, str) and customer.startswith("cus_"):
        return customer
    if isinstance(customer, dict):
        cid = customer.get("id")
        if isinstance(cid, str) and cid.startswith("cus_"):
            return cid
    nested = _nested_subscription(obj)
    if nested is not None and nested is not obj:
        return _customer_id_from_obj(nested)
    return None


def _stripe_secret_key() -> str | None:
    key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    return key or None


def _stripe_to_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if value is None:
        return None
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        return data if isinstance(data, dict) else None
    try:
        return dict(value)
    except Exception:
        return None


def retrieve_stripe_subscription(subscription_id: str) -> dict[str, Any] | None:
    """Fetch a Subscription by id using STRIPE_SECRET_KEY. Returns None on failure."""
    secret = _stripe_secret_key()
    if not secret or not subscription_id:
        return None
    try:
        import stripe

        stripe.api_key = secret
        raw = stripe.Subscription.retrieve(subscription_id)
        data = _stripe_to_dict(raw)
        logger.info("Stripe Subscription.retrieve(%s) ok", subscription_id)
        return data
    except Exception:
        logger.exception("Stripe Subscription.retrieve(%s) failed", subscription_id)
        return None


def retrieve_stripe_customer(customer_id: str) -> dict[str, Any] | None:
    """Fetch a Customer by id using STRIPE_SECRET_KEY. Returns None on failure."""
    secret = _stripe_secret_key()
    if not secret or not customer_id:
        return None
    try:
        import stripe

        stripe.api_key = secret
        raw = stripe.Customer.retrieve(customer_id)
        data = _stripe_to_dict(raw)
        logger.info("Stripe Customer.retrieve(%s) ok", customer_id)
        return data
    except Exception:
        logger.exception("Stripe Customer.retrieve(%s) failed", customer_id)
        return None


def retrieve_stripe_invoice(
    invoice_id: str,
    *,
    expand: list[str] | None = None,
) -> dict[str, Any] | None:
    """Fetch an Invoice by id (optional expand) using STRIPE_SECRET_KEY."""
    secret = _stripe_secret_key()
    if not secret or not invoice_id:
        return None
    try:
        import stripe

        stripe.api_key = secret
        kwargs: dict[str, Any] = {}
        if expand:
            kwargs["expand"] = expand
        raw = stripe.Invoice.retrieve(invoice_id, **kwargs)
        data = _stripe_to_dict(raw)
        logger.info("Stripe Invoice.retrieve(%s) ok expand=%s", invoice_id, expand)
        return data
    except Exception:
        logger.exception("Stripe Invoice.retrieve(%s) failed", invoice_id)
        return None


def _iter_item_dicts(container: Any) -> list[dict[str, Any]]:
    """Normalize Stripe list / {data: [...]} / bare list containers to dict items."""
    items: list[Any] = []
    if isinstance(container, dict):
        items = list(container.get("data") or [])
    elif isinstance(container, list):
        items = container
    return [i for i in items if isinstance(i, dict)]


def period_end_from_stripe_object(obj: dict[str, Any]) -> datetime | None:
    """Best-effort period end from Stripe event objects.

    Sources (in order):
    - top-level ``current_period_end`` / ``period_end``
    - subscription ``items.data[].current_period_end`` (newer API: no top-level period)
    - invoice / checkout line ``period.end``
    - expanded nested subscription (recursive)
    """
    for key in ("current_period_end", "period_end"):
        dt = _ts_to_utc(obj.get(key))
        if dt is not None:
            return dt

    # Newer Subscription API: period lives on subscription items, not the root.
    ends: list[datetime] = []
    for item in _iter_item_dicts(obj.get("items")):
        dt = _ts_to_utc(item.get("current_period_end"))
        if dt is not None:
            ends.append(dt)
        period = item.get("period")
        if isinstance(period, dict):
            dt = _ts_to_utc(period.get("end"))
            if dt is not None:
                ends.append(dt)

    # invoice / checkout line items carry period.end
    for container_key in ("lines", "line_items"):
        for item in _iter_item_dicts(obj.get(container_key)):
            period = item.get("period")
            if isinstance(period, dict):
                dt = _ts_to_utc(period.get("end"))
                if dt is not None:
                    ends.append(dt)
    if ends:
        return max(ends)

    nested = _nested_subscription(obj)
    if nested is not None and nested is not obj:
        return period_end_from_stripe_object(nested)
    return None


def resolve_period_end_for_mint(obj: dict[str, Any]) -> datetime | None:
    """Resolve period end, retrieving the Subscription when only a string id is present."""
    dt = period_end_from_stripe_object(obj)
    if dt is not None:
        return dt

    # Already an expanded nested subscription without period — try retrieve by id.
    sid = _subscription_id_from_obj(obj)
    if not sid:
        return None

    # Avoid redundant retrieve when obj itself is the subscription we already inspected.
    if obj.get("object") == "subscription" and obj.get("id") == sid:
        # Still try retrieve in case webhook payload was thin vs API.
        logger.info(
            "period_end missing on subscription object %s; retrieving from Stripe API",
            sid,
        )
    elif isinstance(obj.get("subscription"), dict):
        # Expanded nested sub already walked by period_end_from_stripe_object.
        logger.info(
            "period_end missing on expanded subscription %s; retrieving from Stripe API",
            sid,
        )
    else:
        logger.info(
            "period_end missing and subscription is id %s; retrieving from Stripe API",
            sid,
        )

    retrieved = retrieve_stripe_subscription(sid)
    if retrieved is None:
        logger.warning("Cannot resolve period_end: Subscription.retrieve(%s) failed", sid)
        return None
    dt = period_end_from_stripe_object(retrieved)
    if dt is None:
        logger.warning(
            "Subscription.retrieve(%s) returned no usable current_period_end",
            sid,
        )
    else:
        logger.info(
            "Resolved period_end=%s via Subscription.retrieve(%s)",
            dt.isoformat(),
            sid,
        )
    return dt


def resolve_customer_email(obj: dict[str, Any], email: str | None = None) -> str | None:
    """Fill missing email via metadata / expanded customer / Customer.retrieve."""
    if email and "@" in email:
        return email.strip()

    # Re-check common fields (subscription.created Payment Link payloads are thin).
    for extractor in (_email_from_checkout_session, _email_from_invoice, _email_from_subscription):
        got = extractor(obj)
        if got:
            return got

    customer = obj.get("customer")
    if isinstance(customer, dict):
        got = (customer.get("email") or "").strip()
        if got and "@" in got:
            return got

    cid = _customer_id_from_obj(obj)
    if cid:
        cust = retrieve_stripe_customer(cid)
        if cust:
            got = (cust.get("email") or "").strip()
            if got and "@" in got:
                logger.info("Resolved customer email via Customer.retrieve(%s)", cid)
                return got
            logger.warning("Customer.retrieve(%s) returned no email", cid)
        else:
            logger.warning("Cannot resolve email: Customer.retrieve(%s) failed", cid)

    nested = _nested_subscription(obj)
    if nested is not None and nested is not obj:
        return resolve_customer_email(nested, None)
    return None


def ensure_subscription_expanded(obj: dict[str, Any]) -> dict[str, Any]:
    """When ``subscription`` is a string id, retrieve and attach the dict (copy)."""
    sub = obj.get("subscription")
    if isinstance(sub, dict):
        return obj
    sid = _subscription_id_from_obj(obj)
    if not sid:
        return obj
    if obj.get("object") == "subscription":
        return obj
    retrieved = retrieve_stripe_subscription(sid)
    if retrieved is None:
        logger.warning(
            "Leaving subscription as id %s — retrieve failed (cancel/period may be incomplete)",
            sid,
        )
        return obj
    logger.info("Expanded subscription id %s via Subscription.retrieve for mint checks", sid)
    return {**obj, "subscription": retrieved}


def enrich_price_ok(obj: dict[str, Any], price_ok: bool) -> bool:
    """Second-chance Pro price match when webhook lines are thin / new pricing shape."""
    if price_ok or _matches_pro_price(obj):
        return True
    expected = pro_price_id()
    if not expected:
        return True
    # Definitive mismatch if we already saw other price ids.
    prices = _price_ids_from_obj(obj)
    if prices:
        return False

    # Thin invoice: retrieve with expand so pricing.price_details / subscription items appear.
    if obj.get("object") == "invoice":
        iid = obj.get("id")
        if isinstance(iid, str) and iid.startswith("in_"):
            inv = retrieve_stripe_invoice(
                iid,
                expand=[
                    "lines.data.price",
                    "lines.data.pricing.price_details.price",
                    "subscription",
                    "subscription.items.data.price",
                ],
            )
            if inv and _matches_pro_price(inv):
                logger.info("Pro price matched via Invoice.retrieve(%s)", iid)
                return True

    sid = _subscription_id_from_obj(obj)
    if sid and obj.get("object") != "subscription":
        sub = obj.get("subscription") if isinstance(obj.get("subscription"), dict) else None
        if sub is None:
            sub = retrieve_stripe_subscription(sid)
        if sub and _matches_pro_price(sub):
            logger.info("Pro price matched via Subscription.retrieve(%s)", sid)
            return True
    return False


def _log_ignored_or_error(result: IssuanceResult, event_type: str) -> IssuanceResult:
    """INFO-log every ignored/error outcome so ops can see remint failures."""
    if result.status in ("ignored", "error"):
        logger.info(
            "Stripe issuance %s: event_id=%s event_type=%s reason=%s email=%s session_id=%s",
            result.status,
            result.event_id,
            event_type or "",
            result.reason,
            result.email,
            result.session_id,
        )
    return result


def subscription_will_not_renew(obj: dict[str, Any]) -> bool:
    """True when the subscription is canceled or scheduled not to renew.

    Used so ``invoice.paid`` (and equivalent mint events) do not refresh/extend a
    license after cancel — the customer keeps any key already minted for the paid
    period, which expires at that period end.

    Only subscription-shaped objects are inspected (never invoice ``status``, which
    uses a different enum).
    """
    candidates: list[dict[str, Any]] = []
    # subscription.created / expanded subscription on checkout or invoice
    if obj.get("object") == "subscription" or "cancel_at_period_end" in obj:
        candidates.append(obj)
    nested = _nested_subscription(obj)
    if nested is not None:
        candidates.append(nested)

    for cand in candidates:
        status = str(cand.get("status") or "").lower()
        if status in ("canceled", "unpaid", "incomplete_expired"):
            return True
        if cand.get("cancel_at_period_end") is True:
            return True
        if cand.get("canceled_at") is not None and status in ("canceled", ""):
            return True
    return False


def mint_pro_license(*, email: str, expires_at: datetime | None = None) -> str:
    """Sign a Pro dmtl1 key for the customer email.

    Stripe-minted keys MUST pass ``expires_at`` from the subscription period end
    (not perpetual). Manual comps via ``make license-issue`` / ``issue_license.py``
    may omit ``expires_at`` for a perpetual key.
    """
    payload = LicensePayload(
        tier="pro",
        issued_at=datetime.now(UTC),
        expires_at=expires_at,
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

    def _done(result: IssuanceResult) -> IssuanceResult:
        return _log_ignored_or_error(result, event_type)

    if event_id:
        prior = store.get_by_event(event_id)
        if prior is not None:
            logger.info("Stripe event %s already processed (%s) — idempotent replay", event_id, prior.status)
            return _done(
                IssuanceResult(
                    status="replay",
                    event_id=event_id,
                    email=prior.email,
                    license_key=prior.license_key,
                    session_id=prior.session_id,
                    reason="already_processed",
                    delivered_via=prior.delivered_via,
                )
            )

    if event_type not in _HANDLED_EVENTS:
        return _done(
            IssuanceResult(
                status="ignored",
                event_id=event_id or "unknown",
                reason=f"unhandled_event:{event_type}",
            )
        )

    data = event.get("data") or {}
    obj = data.get("object") if isinstance(data, dict) else None
    if not isinstance(obj, dict):
        # stripe Event data.object may be a StripeObject
        if obj is not None and hasattr(obj, "to_dict"):
            obj = obj.to_dict()
        else:
            return _done(
                IssuanceResult(
                    status="ignored",
                    event_id=event_id or "unknown",
                    reason="missing_data_object",
                )
            )

    # Payment Link webhooks often send subscription as a string id — expand for
    # cancel / period / price checks when possible.
    obj = ensure_subscription_expanded(obj)

    email, session_id, price_ok = _extract_mint_context(event_type, obj)
    price_ok = enrich_price_ok(obj, price_ok)
    email = resolve_customer_email(obj, email)

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
            return _done(result)

    if not price_ok:
        return _done(
            IssuanceResult(
                status="ignored",
                event_id=event_id or "unknown",
                email=email,
                session_id=session_id,
                reason="price_mismatch_or_unpaid",
            )
        )

    if not email:
        return _done(
            IssuanceResult(
                status="ignored",
                event_id=event_id or "unknown",
                session_id=session_id,
                reason="missing_customer_email",
            )
        )

    # No renew after cancel: do not mint/refresh when sub is canceled / won't renew.
    if subscription_will_not_renew(obj):
        return _done(
            IssuanceResult(
                status="ignored",
                event_id=event_id or "unknown",
                email=email,
                session_id=session_id,
                reason="subscription_canceled_or_non_renewing",
            )
        )

    expires_at = resolve_period_end_for_mint(obj)
    if expires_at is None:
        return _done(
            IssuanceResult(
                status="ignored",
                event_id=event_id or "unknown",
                email=email,
                session_id=session_id,
                reason="missing_period_end",
            )
        )

    try:
        license_key = mint_pro_license(email=email, expires_at=expires_at)
    except Exception as e:
        logger.exception("Failed to mint license for %s", email)
        return _done(
            IssuanceResult(
                status="error",
                event_id=event_id or "unknown",
                email=email,
                session_id=session_id,
                reason=f"mint_failed:{e}",
            )
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
    return _done(result)



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
