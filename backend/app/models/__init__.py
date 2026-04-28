from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import every model so Base.metadata sees them (used by Alembic autogenerate).
from app.models.connection import Connection  # noqa: E402, F401
from app.models.schema_snapshot import SchemaSnapshot  # noqa: E402, F401
from app.models.comparison import Comparison  # noqa: E402, F401
from app.models.mapping import Mapping  # noqa: E402, F401
from app.models.migration_run import MigrationRun, MigrationRunStatus  # noqa: E402, F401
from app.models.migration_run_table import (  # noqa: E402, F401
    ConflictMode,
    MigrationRunTable,
    TableRunStatus,
)
from app.models.verification_run import VerificationRun, VerificationRunStatus  # noqa: E402, F401
from app.models.verification_run_table import (  # noqa: E402, F401
    VerificationRunTable,
    VerificationTableStatus,
)

__all__ = [
    "Base",
    "Connection",
    "SchemaSnapshot",
    "Comparison",
    "Mapping",
    "MigrationRun",
    "MigrationRunStatus",
    "MigrationRunTable",
    "TableRunStatus",
    "ConflictMode",
    "VerificationRun",
    "VerificationRunStatus",
    "VerificationRunTable",
    "VerificationTableStatus",
]
