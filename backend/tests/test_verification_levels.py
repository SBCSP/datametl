"""Sanity-check the verification level → check name mapping. Live-DB tests for the
individual checks happen via the sample compose profile, not pytest."""
from __future__ import annotations

from app.verification.runner import LEVELS


def test_count_only_runs_count_and_sequence():
    assert "row_count" in LEVELS["count_only"]
    assert "sequence_parity" in LEVELS["count_only"]
    assert "hash_sample" not in LEVELS["count_only"]


def test_count_and_sample_runs_three_checks():
    assert set(LEVELS["count_and_sample"]) == {"row_count", "hash_sample", "sequence_parity"}


def test_full_hash_currently_falls_back_to_sample():
    # full_hash is a v1.5 feature; until it lands the level acts as count_and_sample.
    assert set(LEVELS["count_sample_and_full_hash"]) == {"row_count", "hash_sample", "sequence_parity"}
