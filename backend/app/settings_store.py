"""Persisted, encrypted app settings (currently just the Anthropic API key).

Values are stored Fernet-encrypted (via the same `vault` used for connection credentials) in
the `app_settings` table, keyed by a short string. Never returns ciphertext or the raw key from
the API layer — only the decrypted value to internal callers (the chat endpoint).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.crypto import vault
from app.models.app_setting import AppSetting

_ANTHROPIC_KEY = "anthropic_api_key"


def get_anthropic_key(db: Session) -> str | None:
    row = db.get(AppSetting, _ANTHROPIC_KEY)
    if row is None:
        return None
    value = vault.decrypt(row.encrypted_value).get(_ANTHROPIC_KEY)
    return value or None


def has_anthropic_key(db: Session) -> bool:
    return get_anthropic_key(db) is not None


def set_anthropic_key(db: Session, api_key: str | None) -> None:
    """Set (upsert) or, when api_key is empty/None, clear the stored Anthropic key."""
    if not api_key or not api_key.strip():
        clear_anthropic_key(db)
        return
    encrypted = vault.encrypt({_ANTHROPIC_KEY: api_key.strip()})
    row = db.get(AppSetting, _ANTHROPIC_KEY)
    if row is None:
        db.add(AppSetting(key=_ANTHROPIC_KEY, encrypted_value=encrypted))
    else:
        row.encrypted_value = encrypted
    db.commit()


def clear_anthropic_key(db: Session) -> None:
    row = db.get(AppSetting, _ANTHROPIC_KEY)
    if row is not None:
        db.delete(row)
        db.commit()


# --- Mel tool approval mode (non-secret preference, still Fernet-wrapped for one store) ---

_MEL_TOOL_APPROVAL = "mel_tool_approval"


def get_mel_tool_approval(db: Session) -> str:
    from app.mcp.approval import APPROVAL_MODES, DEFAULT_APPROVAL_MODE

    row = db.get(AppSetting, _MEL_TOOL_APPROVAL)
    if row is None:
        return DEFAULT_APPROVAL_MODE
    value = vault.decrypt(row.encrypted_value).get(_MEL_TOOL_APPROVAL)
    if value in APPROVAL_MODES:
        return value
    return DEFAULT_APPROVAL_MODE


def set_mel_tool_approval(db: Session, mode: str) -> str:
    from app.mcp.approval import APPROVAL_MODES, DEFAULT_APPROVAL_MODE

    mode = (mode or "").strip() or DEFAULT_APPROVAL_MODE
    if mode not in APPROVAL_MODES:
        raise ValueError(f"Invalid mel_tool_approval mode: {mode}")
    encrypted = vault.encrypt({_MEL_TOOL_APPROVAL: mode})
    row = db.get(AppSetting, _MEL_TOOL_APPROVAL)
    if row is None:
        db.add(AppSetting(key=_MEL_TOOL_APPROVAL, encrypted_value=encrypted))
    else:
        row.encrypted_value = encrypted
    db.commit()
    return mode
