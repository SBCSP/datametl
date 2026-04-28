"""Migration verification framework.

Each check is a small focused class implementing `run(src_engine, dst_engine, ctx)` and
returning a `CheckResult`. The runner picks which checks to run based on the
`verification` level set per-table.
"""
from app.verification.base import Check, CheckContext, CheckResult
from app.verification.runner import LEVELS, run_checks

__all__ = ["Check", "CheckContext", "CheckResult", "LEVELS", "run_checks"]
