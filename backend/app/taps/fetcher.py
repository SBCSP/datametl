"""Fetch JSON from a REST endpoint and extract the records to land.

Bounded for safety: http/https only, a request timeout, and a response-size cap (the operator
configures the URL, so SSRF is acceptable for this local-first tool, but we still don't want to OOM
the worker on a giant body). Returns the parsed records as a list — each element becomes one JSONB
row downstream (objects and scalars both land fine).
"""
from __future__ import annotations

from typing import Any

import httpx

MAX_RESPONSE_BYTES = 25 * 1024 * 1024  # 25 MB
DEFAULT_TIMEOUT_S = 30.0


def resolve_records(payload: Any, records_path: str) -> list[Any]:
    """Walk `records_path` (dot path) into the payload, then normalize to a list of records.

    Empty path → use the whole response. A list becomes the rows; anything else (object/scalar)
    becomes a single row. A path that doesn't resolve yields no records.
    """
    node = payload
    if records_path:
        for part in (p.strip() for p in records_path.split(".") if p.strip()):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return []
            if node is None:
                return []
    if node is None:
        return []
    return node if isinstance(node, list) else [node]


async def fetch(
    *,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    body: str | None = None,
    records_path: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Perform the request and return {http_status, records}. Raises ValueError on bad input/response."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")

    verb = (method or "GET").upper()
    kwargs: dict[str, Any] = {}
    if query_params:
        kwargs["params"] = query_params
    if headers:
        kwargs["headers"] = headers
    if body and verb not in ("GET", "HEAD"):
        kwargs["content"] = body

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        resp = await client.request(verb, url, **kwargs)

    if len(resp.content) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response too large (> {MAX_RESPONSE_BYTES // (1024 * 1024)} MB)")

    try:
        payload = resp.json()
    except Exception as e:
        snippet = resp.text[:200]
        raise ValueError(f"response was not valid JSON (HTTP {resp.status_code}): {snippet}") from e

    return {"http_status": resp.status_code, "records": resolve_records(payload, records_path)}
