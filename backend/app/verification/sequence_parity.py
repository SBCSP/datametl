"""SequenceParityCheck — make sure dest sequences are advanced past current MAX(pk).

This catches a classic data-migration footgun: after bulk-loading existing rows with their
original PK values, the dest sequence's last_value is still wherever Postgres initialized it
(usually 1), so the very next INSERT will collide with row 1's PK.

The LogicalCopyStrategy already runs `setval()` post-COPY. This check verifies that landed.
"""
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


class SequenceParityCheck(Check):
    name = "sequence_parity"

    def run(self, src_engine, dst_engine, ctx: CheckContext) -> CheckResult:
        dst_s, dst_t = _split_qn(ctx.dest_table)

        try:
            with dst_engine.connect() as dst:
                rows = dst.execute(
                    text(
                        """
                        SELECT column_name, pg_get_serial_sequence(:fqn, column_name) AS seq
                        FROM information_schema.columns
                        WHERE table_schema = :s AND table_name = :t
                        """
                    ),
                    {"fqn": f"{dst_s}.{dst_t}", "s": dst_s, "t": dst_t},
                ).all()

                cols_with_seqs = [(r.column_name, r.seq) for r in rows if r.seq]
                if not cols_with_seqs:
                    return CheckResult(
                        self.name, passed=True, detail="no sequence-backed columns",
                        metrics={"sequences": []},
                    )

                results = []
                all_ok = True
                for col, seq in cols_with_seqs:
                    max_val = dst.execute(
                        text(f'SELECT max({_q(col)}) FROM {_q(dst_s)}.{_q(dst_t)}')  # noqa: S608
                    ).scalar()
                    if max_val is None:
                        results.append({"column": col, "sequence": seq, "max": None, "last_value": None, "ok": True})
                        continue
                    last_val = dst.execute(
                        text(f"SELECT last_value FROM {seq}")  # noqa: S608
                    ).scalar()
                    ok = last_val is not None and last_val >= max_val
                    if not ok:
                        all_ok = False
                    results.append(
                        {
                            "column": col,
                            "sequence": seq,
                            "max": int(max_val),
                            "last_value": int(last_val) if last_val is not None else None,
                            "ok": ok,
                        }
                    )

        except Exception as e:  # noqa: BLE001
            return CheckResult(self.name, passed=False, detail="check raised", error=str(e))

        if all_ok:
            detail = f"{len(results)} sequence(s) at or ahead of max(pk)"
        else:
            behind = [r for r in results if not r["ok"]]
            detail = f"BEHIND: {len(behind)} sequence(s) behind their column max"
        return CheckResult(name=self.name, passed=all_ok, detail=detail, metrics={"sequences": results})
