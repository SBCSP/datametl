"""Migration execution: plan, pre-flight, runner, DDL preview.

The user-facing flow:
    1. Build a plan from a Comparison + per-table options.
    2. Pre-flight (read-only) to validate connectivity, dst tables exist, mappings cover columns, etc.
    3. Run — executes each included table via a Strategy (LogicalCopyStrategy in v1),
       then runs verification checks, then records results on MigrationRunTable rows.
"""
