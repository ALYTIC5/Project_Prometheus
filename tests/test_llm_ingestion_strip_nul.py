"""Pure-function test for ingestion.py's NUL-byte sanitization -- no DB
needed, unlike the rest of tests/test_llm_ingestion.py (module-marked
`db`), so this actually runs locally instead of skipping."""
from __future__ import annotations

from prometheus.research.llm.ingestion import _strip_nul


def test_strip_nul_removes_embedded_null_bytes() -> None:
    """Real production crash: pypdf's extract_text() emitted a 0x00 byte
    from a PDF's internal encoding quirk, and Postgres's text columns
    reject NUL bytes outright (asyncpg CharacterNotInRepertoireError)
    even though they're valid UTF-8 -- confirmed via worker logs."""
    assert _strip_nul("abc\x00def") == "abcdef"


def test_strip_nul_is_a_no_op_on_clean_text() -> None:
    assert _strip_nul("clean text, no surprises") == "clean text, no surprises"
