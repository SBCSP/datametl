from __future__ import annotations

import os

# Tests need ENCRYPTION_KEY + DATABASE_URL set just so app modules can import. The DB URL
# is never connected to in the pure-logic tests below.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    # A valid Fernet key (urlsafe base64, 32 bytes). Test-only.
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
