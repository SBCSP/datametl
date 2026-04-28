"""HashSampleCheck — sample N rows by primary key on the source, hash each one with
md5(row_to_json(t)::text), then look up the same PK on the destination and compare hashes.

Sample size: min(1000, max(100, total_rows * 0.01)) — at least 100 rows or 1% of the
table, whichever is larger, capped at 1000 to keep cost predictable.

Limitations:
  - Only runs against tables with a single-column PK. Composite PKs and PK-less tables
    skip with a "passed=True, detail=skipped" result.
  - The check fetches matching rows using their PK; it doesn't *currently* report rows
    that exist on source but are missing on dest (the row count check covers that broad
    failure mode). It does flag mismatched-content rows via the hash comparison.
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


class HashSampleCheck(Check):
    name = "hash_sample"

    def run(self, src_engine, dst_engine, ctx: CheckContext) -> CheckResult:
        src_s, src_t = _split_qn(ctx.source_table)
        dst_s, dst_t = _split_qn(ctx.dest_table)

        try:
            with src_engine.connect() as src, dst_engine.connect() as dst:
                pk_col = _single_column_pk(src, src_s, src_t)
                if pk_col is None:
                    return CheckResult(
                        self.name, passed=True, detail="skipped — no single-column PK to sample on",
                        metrics={"skipped": True},
                    )

                row_total = src.execute(
                    text(f"SELECT count(*) FROM {_q(src_s)}.{_q(src_t)}")  # noqa: S608
                ).scalar_one()
                if row_total == 0:
                    return CheckResult(
                        self.name, passed=True, detail="empty table — nothing to sample",
                        metrics={"sample_size": 0, "checked": 0},
                    )

                sample_size = min(1000, max(100, int(row_total * 0.01)))
                sample_size = min(sample_size, int(row_total))

                # Pull a random sample with their MD5(row_to_json) on the source side.
                src_rows = src.execute(
                    text(
                        f"""
                        SELECT {_q(pk_col)} AS pk, md5(row_to_json(t)::text) AS h
                        FROM {_q(src_s)}.{_q(src_t)} t
                        ORDER BY random()
                        LIMIT :n
                        """  # noqa: S608
                    ),
                    {"n": sample_size},
                ).all()
                src_hashes = {r.pk: r.h for r in src_rows}

                if not src_hashes:
                    return CheckResult(
                        self.name, passed=True, detail="empty sample",
                        metrics={"sample_size": 0, "checked": 0},
                    )

                # Look up the same PKs on the destination.
                pks = list(src_hashes.keys())
                dst_rows = dst.execute(
                    text(
                        f"""
                        SELECT {_q(pk_col)} AS pk, md5(row_to_json(t)::text) AS h
                        FROM {_q(dst_s)}.{_q(dst_t)} t
                        WHERE {_q(pk_col)} = ANY(:pks)
                        """  # noqa: S608
                    ),
                    {"pks": pks},
                ).all()
                dst_hashes = {r.pk: r.h for r in dst_rows}

        except Exception as e:  # noqa: BLE001
            return CheckResult(self.name, passed=False, detail="check raised", error=str(e))

        missing: list = []
        mismatched: list = []
        for pk, src_h in src_hashes.items():
            if pk not in dst_hashes:
                missing.append(pk)
            elif dst_hashes[pk] != src_h:
                mismatched.append(pk)

        passed = not missing and not mismatched
        n = len(src_hashes)
        if passed:
            detail = f"{n} sampled rows match"
        else:
            parts = []
            if missing:
                parts.append(f"{len(missing)} missing on dest")
            if mismatched:
                parts.append(f"{len(mismatched)} content mismatches")
            detail = "MISMATCH: " + ", ".join(parts) + f" (sampled {n})"

        return CheckResult(
            name=self.name,
            passed=passed,
            detail=detail,
            metrics={
                "sample_size": n,
                "missing": [str(x) for x in missing[:10]],
                "mismatched": [str(x) for x in mismatched[:10]],
                "missing_count": len(missing),
                "mismatched_count": len(mismatched),
                "pk_column": pk_col,
            },
        )


def _single_column_pk(conn, schema: str, table: str) -> str | None:
    """Return the PK column name only if there's exactly one PK column. None otherwise."""
    rows = conn.execute(
        text(
            """
            SELECT a.attname AS column_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :s AND c.relname = :t AND i.indisprimary
            """
        ),
        {"s": schema, "t": table},
    ).all()
    if len(rows) == 1:
        return rows[0].column_name
    return None
