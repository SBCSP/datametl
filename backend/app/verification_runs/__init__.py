"""Standalone verification runs.

Verification reads both source and destination, runs the configured checks per table,
and reports parity. It writes nothing to either user database — only to the
verification_run_tables row in DataMETL's metadata DB.

Lives in a separate module from `app.verification` (which holds the check classes) so the
distinction is clear: `verification/` = check implementations; `verification_runs/` =
orchestration of standalone parity audits.
"""
