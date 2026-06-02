from __future__ import annotations

from app.scripts.runner import cap_rows, split_statements


def test_split_multiple_statements():
    stmts = split_statements("SELECT 1; SELECT 2;\nSELECT 3")
    assert stmts == ["SELECT 1", "SELECT 2", "SELECT 3"]


def test_split_ignores_semicolons_inside_string_literals():
    sql = "SELECT 'a;b' AS x; SELECT 2"
    assert split_statements(sql) == ["SELECT 'a;b' AS x", "SELECT 2"]


def test_split_ignores_semicolons_inside_dollar_quotes():
    sql = "SELECT $$ a; b; c $$ AS x; SELECT 2"
    stmts = split_statements(sql)
    assert stmts == ["SELECT $$ a; b; c $$ AS x", "SELECT 2"]


def test_split_drops_comment_only_and_empty_fragments():
    # A lone ";" (empty) and a fragment that is nothing but a comment are dropped.
    sql = "SELECT 1;\n;\n-- a trailing comment only\n"
    assert split_statements(sql) == ["SELECT 1"]


def test_split_keeps_leading_comment_attached_to_statement():
    # We never rewrite the user's SQL: a comment preceding a statement rides along with it
    # (Postgres ignores it at execution time), rather than being stripped or split off.
    stmts = split_statements("-- header\nSELECT 1")
    assert len(stmts) == 1
    assert stmts[0].startswith("-- header")
    assert stmts[0].endswith("SELECT 1")


def test_split_empty_input():
    assert split_statements("") == []
    assert split_statements("   \n  ;;  ") == []


def test_cap_rows_under_cap_not_truncated():
    capped, truncated = cap_rows([1, 2, 3], 5)
    assert capped == [1, 2, 3]
    assert truncated is False


def test_cap_rows_exactly_at_cap_not_truncated():
    capped, truncated = cap_rows([1, 2, 3], 3)
    assert capped == [1, 2, 3]
    assert truncated is False


def test_cap_rows_over_cap_truncates():
    # Caller fetches cap+1 to detect the overflow; cap_rows slices back to cap.
    capped, truncated = cap_rows([1, 2, 3, 4], 3)
    assert capped == [1, 2, 3]
    assert truncated is True
