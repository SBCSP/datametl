"""RowCountCheck — `count(*)` parity between source and destination, with tolerance.

Strict equality fails the check on noisy live sources where a few rows churn during the
migration window (new chat messages, expired sessions, audit log writes, etc.). We allow
a small drift before flagging — anything bigger almost certainly means a real loss/dupe.
"""
from __future__ import annotations

from sqlalchemy import text

from app.verification.base import Check, CheckContext, CheckResult

# Tolerance: pass if |delta| ≤ 0.1% OF source rows, OR ≤ 100 rows absolute (whichever
# is greater). Tuned for "live prod source" reality — small enough to catch real data
# loss on big tables, generous enough to ignore expected churn during a multi-minute load.
_TOLERANCE_FRACTION = 0.001
_TOLERANCE_FLOOR = 100


def _split_qn(qn: str) -> tuple[str, str]:
    if "." in qn:
        s, _, t = qn.partition(".")
        return s, t
    return "public", qn


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


class RowCountCheck(Check):
    name = "row_count"

    def run(self, src_engine, dst_engine, ctx: CheckContext) -> CheckResult:
        src_s, src_t = _split_qn(ctx.source_table)
        dst_s, dst_t = _split_qn(ctx.dest_table)

        try:
            with src_engine.connect() as src, dst_engine.connect() as dst:
                src_n = src.execute(
                    text(f"SELECT count(*) FROM {_q(src_s)}.{_q(src_t)}")  # noqa: S608
                ).scalar_one()
                dst_n = dst.execute(
                    text(f"SELECT count(*) FROM {_q(dst_s)}.{_q(dst_t)}")  # noqa: S608
                ).scalar_one()
        except Exception as e:  # noqa: BLE001
            return CheckResult(self.name, passed=False, detail="check raised", error=str(e))

        delta = dst_n - src_n
        tolerance = max(_TOLERANCE_FLOOR, int(src_n * _TOLERANCE_FRACTION))
        within_tolerance = abs(delta) <= tolerance
        exact_match = delta == 0

        if exact_match:
            detail = f"source={src_n:,} dest={dst_n:,} (exact match)"
        elif within_tolerance:
            detail = (
                f"source={src_n:,} dest={dst_n:,} (delta {delta:+,}, within ±{tolerance:,} "
                f"tolerance — likely live-source churn during the migration window)"
            )
        else:
            detail = (
                f"MISMATCH: source={src_n:,} dest={dst_n:,} (delta {delta:+,}, exceeds "
                f"±{tolerance:,} tolerance)"
            )

        return CheckResult(
            name=self.name,
            passed=within_tolerance,
            detail=detail,
            metrics={
                "source": int(src_n),
                "dest": int(dst_n),
                "delta": int(delta),
                "tolerance": int(tolerance),
                "exact_match": exact_match,
            },
        )
