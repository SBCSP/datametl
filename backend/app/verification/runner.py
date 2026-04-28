"""Runs the configured checks for a table; returns list[CheckResult]."""
from __future__ import annotations

from app.verification.base import CheckContext, CheckResult
from app.verification.hash_sample import HashSampleCheck
from app.verification.row_count import RowCountCheck
from app.verification.sequence_parity import SequenceParityCheck

# Maps a verification level (set in TableOption.verification) to the list of checks that run.
LEVELS = {
    "count_only": ["row_count", "sequence_parity"],
    "count_and_sample": ["row_count", "hash_sample", "sequence_parity"],
    "count_sample_and_full_hash": ["row_count", "hash_sample", "sequence_parity"],  # full_hash TBD in v1.5
}

_CHECKS = {
    "row_count": RowCountCheck(),
    "hash_sample": HashSampleCheck(),
    "sequence_parity": SequenceParityCheck(),
}


def run_checks(src_engine, dst_engine, *, level: str, ctx: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in LEVELS.get(level, LEVELS["count_and_sample"]):
        check = _CHECKS[name]
        results.append(check.run(src_engine, dst_engine, ctx))
    return results
