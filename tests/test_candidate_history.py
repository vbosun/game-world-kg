from __future__ import annotations

import json

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.worldspec import sample_world_spec
from game_world_kg.worldspec_draft_repository import CandidateRepository, RawDraftRepository


def test_repaired_json_creates_patch_history_versions() -> None:
    """submit_repaired_json must record previous version in patch_history before overwriting."""
    conn = connect(":memory:")
    init_db(conn)

    candidate_id: str
    with transaction(conn):
        raw_repo = RawDraftRepository(conn)
        cand_repo = CandidateRepository(conn)

        village = sample_world_spec("village")
        spec_json = json.loads(village.canonical_json())

        raw_id = raw_repo.save(
            trace_id="test_trace",
            idea="test village for patch history",
            provider="test",
            model="test",
            raw_text=json.dumps(spec_json, ensure_ascii=False),
            status="parsed",
        )

        candidate_id = cand_repo.save(
            raw_id=raw_id,
            trace_id="test_trace",
            world_id="test_village_version",
            spec_json=spec_json,
            status="validated",
        )

    # First repair: change title
    with transaction(conn):
        cand_repo = CandidateRepository(conn)
        spec_json["title"] = "修复版本 v1"
        cand_repo.submit_repaired_json(
            candidate_id, spec_json,
            validation_report_json={"valid": True, "issues": []},
        )

    # Second repair: change theme
    with transaction(conn):
        cand_repo = CandidateRepository(conn)
        spec_json["theme"] = "重生与复仇"
        cand_repo.submit_repaired_json(
            candidate_id, spec_json,
            validation_report_json={"valid": True, "issues": []},
        )

    # Verify patch history
    with transaction(conn):
        cand_repo = CandidateRepository(conn)
        history = cand_repo.patch_history(candidate_id)

        # Should have 2 patch entries (original + first repair)
        assert len(history) == 2, f"expected 2 patch versions, got {len(history)}"

        # Versions should be in descending order (latest first)
        assert history[0]["version"] == 2
        assert history[1]["version"] == 1

        # Each patch should have spec_hash
        assert history[0]["spec_hash"] != history[1]["spec_hash"], "each version should have unique spec_hash"
        assert len(history[0]["spec_hash"]) == 64  # SHA-256 hex

        # Current candidate should have the latest repaired spec
        candidate = cand_repo.get(candidate_id)
        assert candidate is not None
        current_spec = json.loads(candidate["spec_json"])
        assert current_spec["title"] == "修复版本 v1"
        assert current_spec["theme"] == "重生与复仇"


def test_patch_history_empty_for_unrepaired_candidate() -> None:
    """A candidate that has never been repaired should have empty patch history."""
    conn = connect(":memory:")
    init_db(conn)

    with transaction(conn):
        raw_repo = RawDraftRepository(conn)
        cand_repo = CandidateRepository(conn)

        village = sample_world_spec("village")
        spec_json = json.loads(village.canonical_json())

        raw_id = raw_repo.save(
            trace_id="test_trace",
            idea="unrepaired village",
            provider="test",
            model="test",
            raw_text=json.dumps(spec_json, ensure_ascii=False),
            status="parsed",
        )

        candidate_id = cand_repo.save(
            raw_id=raw_id,
            trace_id="test_trace",
            world_id="unrepaired_village",
            spec_json=spec_json,
            status="validated",
        )

    with transaction(conn):
        cand_repo = CandidateRepository(conn)
        history = cand_repo.patch_history(candidate_id)
        assert history == []
