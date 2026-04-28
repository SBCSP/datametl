"""Migration execution strategies.

v1 ships `LogicalCopyStrategy` (psycopg streaming binary COPY).
Phase 2.5+ planned: `PgDumpStrategy` (wrap pg_dump | pg_restore for transform-free fast paths)
and `DltStrategy` (cross-engine ETL with schema evolution via dlthub).
"""
from app.strategies.base import Strategy, TableMoveContext, TableMoveResult
from app.strategies.logical_copy import LogicalCopyStrategy

__all__ = ["Strategy", "TableMoveContext", "TableMoveResult", "LogicalCopyStrategy"]
