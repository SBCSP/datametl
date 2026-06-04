from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import every model so Base.metadata sees them (used by Alembic autogenerate).
from app.models.app_setting import AppSetting  # noqa: E402
from app.models.chat_session import ChatSession  # noqa: E402
from app.models.comparison import Comparison  # noqa: E402
from app.models.connection import Connection  # noqa: E402
from app.models.mapping import Mapping  # noqa: E402
from app.models.mcp_session import McpSession  # noqa: E402
from app.models.migration_run import MigrationRun, MigrationRunStatus  # noqa: E402
from app.models.migration_run_table import (  # noqa: E402
    ConflictMode,
    MigrationRunTable,
    TableRunStatus,
)
from app.models.pipeline import (  # noqa: E402
    Pipeline,
    PipelineRun,
    PipelineRunStep,
    PipelineStep,
)
from app.models.scheduled_script import ScheduledRun, ScheduledScript  # noqa: E402
from app.models.schema_snapshot import SchemaSnapshot  # noqa: E402
from app.models.sql_script import SqlScript  # noqa: E402
from app.models.verification_run import VerificationRun, VerificationRunStatus  # noqa: E402
from app.models.verification_run_table import (  # noqa: E402
    VerificationRunTable,
    VerificationTableStatus,
)

__all__ = [
    "AppSetting",
    "Base",
    "ChatSession",
    "Comparison",
    "ConflictMode",
    "Connection",
    "Mapping",
    "McpSession",
    "MigrationRun",
    "MigrationRunStatus",
    "MigrationRunTable",
    "Pipeline",
    "PipelineRun",
    "PipelineRunStep",
    "PipelineStep",
    "ScheduledRun",
    "ScheduledScript",
    "SchemaSnapshot",
    "SqlScript",
    "TableRunStatus",
    "VerificationRun",
    "VerificationRunStatus",
    "VerificationRunTable",
    "VerificationTableStatus",
]
