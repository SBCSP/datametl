"""RowCountCheck — exact `count(*)` parity between source and destination."""
from __future__ import annotations

from sqlalchemy import text

from app.verification.base import Check, CheckContext, CheckResult


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

        passed = src_n == dst_n
        return CheckResult(
            name=self.name,
            passed=passed,
            detail=(
                f"source={src_n:,} dest={dst_n:,}"
                if passed
                else f"MISMATCH: source={src_n:,} dest={dst_n:,} (delta {dst_n - src_n:+,})"
            ),
            metrics={"source": int(src_n), "dest": int(dst_n)},
        )
