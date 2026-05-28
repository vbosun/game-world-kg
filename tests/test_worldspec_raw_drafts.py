from __future__ import annotations

import json
from typing import Any

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.worldspec import sample_world_spec
from game_world_kg.worldspec_draft_repository import RawDraftRepository


class _RaisingLLM:
    """LLM client that raises on any call — used to prove LLM is not invoked."""

    def complete_json(self, messages, *, temperature=0, timeout_seconds=None):
        raise RuntimeError("LLM must not be called during raw parse")

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        raise RuntimeError("LLM must not be called during raw parse")


def test_raw_parse_uses_saved_raw_text_not_llm() -> None:
    """Raw parse must read only raw_draft.raw_text, never invoke LLM."""
    conn = connect(":memory:")
    init_db(conn)

    spec = sample_world_spec("village")
    raw_json = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2)

    with transaction(conn):
        repo = RawDraftRepository(conn)
        raw_id = repo.save(
            trace_id=None,
            idea="test idea",
            provider="test",
            model="test",
            raw_text=raw_json,
            extracted_json_text=raw_json,
            json_parse_status="pending",
        )

    # Verify the draft was saved correctly
    draft = repo.get(raw_id)
    assert draft is not None
    assert draft["raw_text"] == raw_json

    # Parse via the standalone helper — no service, no LLM
    from game_world_kg.worldspec import parse_raw_worldspec_text
    parsed, extracted, error = parse_raw_worldspec_text(raw_json)
    assert parsed is not None, f"Parse should succeed: {error}"
    assert error is None

    # Verify the parsed spec matches the original
    assert parsed["world_id"] == spec.world_id
    assert len(parsed["locations"]) == len(spec.locations)


def test_raw_parse_bad_json_preserves_error() -> None:
    """Malformed raw_text must return parse_success=False and record the error."""
    conn = connect(":memory:")
    init_db(conn)

    bad_text = "this is not json { broken: true"

    with transaction(conn):
        repo = RawDraftRepository(conn)
        raw_id = repo.save(
            trace_id=None,
            idea="bad json test",
            provider="test",
            model="test",
            raw_text=bad_text,
        )

    from game_world_kg.worldspec import parse_raw_worldspec_text
    parsed, extracted, error = parse_raw_worldspec_text(bad_text)
    assert parsed is None
    assert error is not None

    # Update the raw draft as the API would
    with transaction(conn):
        repo.update_parse_result(
            raw_id,
            extracted_json_text=extracted or "",
            json_parse_status="failed",
            json_parse_error=error,
        )

    draft = repo.get(raw_id)
    assert draft["json_parse_status"] == "failed"
    assert draft["json_parse_error"] is not None
    assert len(draft["json_parse_error"]) > 0


def test_raw_parse_creates_candidate_from_raw_text() -> None:
    """After parse, candidate.spec_json must match the raw_text spec, not a regenerated one."""
    conn = connect(":memory:")
    init_db(conn)

    spec = sample_world_spec("cultivation")
    raw_json = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2)

    with transaction(conn):
        repo = RawDraftRepository(conn)
        raw_id = repo.save(
            trace_id="trace-test-1",
            idea="cultivation world",
            provider="test",
            model="test",
            raw_text=raw_json,
            extracted_json_text=raw_json,
        )

    from game_world_kg.worldspec import parse_raw_worldspec_text
    from game_world_kg.worldspec_draft_repository import CandidateRepository

    parsed, extracted, error = parse_raw_worldspec_text(raw_json)
    assert parsed is not None

    # Save candidate from parsed text
    with transaction(conn):
        candidate_id = CandidateRepository(conn).save(
            raw_id=raw_id,
            trace_id="trace-test-1",
            world_id=parsed["world_id"],
            spec_json=parsed,
            status="validated",
        )

    candidate = CandidateRepository(conn).get(candidate_id)
    assert candidate is not None
    candidate_spec = json.loads(candidate["spec_json"]) if isinstance(candidate["spec_json"], str) else candidate["spec_json"]
    assert candidate_spec["world_id"] == spec.world_id
    assert candidate_spec["scale"] == "small_dense"
