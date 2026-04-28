from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CredentialVault:
    """Symmetric encryption for connection credentials.

    The key is read from ENCRYPTION_KEY (a Fernet key, urlsafe base64). Generate one with
    `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    """

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as e:
            raise RuntimeError(
                "ENCRYPTION_KEY is not a valid Fernet key. Run `make key` to generate one."
            ) from e

    def encrypt(self, payload: dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(payload, separators=(",", ":")).encode())

    def decrypt(self, ciphertext: bytes) -> dict[str, Any]:
        try:
            plaintext = self._fernet.decrypt(ciphertext)
        except InvalidToken as e:
            raise RuntimeError("Failed to decrypt credentials — wrong ENCRYPTION_KEY?") from e
        result = json.loads(plaintext)
        if not isinstance(result, dict):
            raise RuntimeError("Decrypted credentials payload is not a JSON object")
        return result


vault = CredentialVault(settings.encryption_key)
