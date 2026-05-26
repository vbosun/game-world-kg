from __future__ import annotations

from game_world_kg.evaluation import (
    evaluate_affordances,
    evaluate_extraction,
    evaluate_llm_extraction,
    evaluate_npc_memory,
    evaluate_quests,
    evaluate_replay,
    evaluate_three_store_demo_village,
    run_evaluation,
)


def test_evaluate_extraction_reports_schema_evidence_and_scope_safety() -> None:
    result = evaluate_extraction()

    assert result["case_count"] == 4
    assert result["schema_pass_rate"] == 1.0
    assert result["evidence_coverage_rate"] == 1.0
    assert result["canonical_error_rate"] == 0.0
    assert result["illegal_or_uncertain_downgrade_rate"] == 1.0


def test_evaluate_llm_extraction_reports_scope_safety() -> None:
    result = evaluate_llm_extraction()

    assert result["case_count"] == 2
    assert result["llm_calls"] == 2
    assert result["schema_pass_rate"] == 1.0
    assert result["scope_accuracy"] == 1.0
    assert result["evidence_coverage_rate"] == 1.0
    assert result["canonical_error_rate"] == 0.0


def test_evaluate_replay_reports_perfect_local_replay() -> None:
    result = evaluate_replay(event_count=100)

    assert result["event_count"] == 100
    assert result["latest_reputation"] == 100
    assert result["midpoint_reputation"] == 50
    assert result["replay_accuracy"] == 1.0
    assert result["llm_calls_during_replay"] == 0


def test_evaluate_affordances_reports_action_validity() -> None:
    result = evaluate_affordances()

    assert result["passed_cases"] == result["case_count"]
    assert result["illegal_action_block_rate"] == 1.0
    assert result["action_relevant_rate"] == 1.0


def test_evaluate_npc_memory_reports_scope_safety() -> None:
    result = evaluate_npc_memory()

    assert result["memory_correct_rate"] == 1.0
    assert result["npc_privileged_knowledge_rate"] == 0.0
    assert result["canonical_pollution_rate"] == 0.0


def test_evaluate_quests_reports_dependency_traceability_and_completion() -> None:
    result = evaluate_quests()

    assert result["quest_count"] == 3
    assert result["quest_dependency_valid_rate"] == 1.0
    assert result["quest_traceability_rate"] == 1.0
    assert result["quest_completable_rate"] == 1.0
    assert result["quest_reward_valid_rate"] == 1.0
    assert result["quest_failure_valid_rate"] == 1.0


def test_evaluate_three_store_demo_village_reports_consistency_and_resolution() -> None:
    result = evaluate_three_store_demo_village()

    assert result["projector_rebuild_consistency"] == 1.0
    assert result["kuzu_graph_query_correct"] == 1.0
    assert result["chroma_memory_query_correct"] == 1.0
    assert result["chroma_scope_leak_rate"] == 0.0
    assert result["demo_village_movement_coverage"] >= 1.0
    assert result["tension_resolution_rate"] == 1.0


def test_run_evaluation_returns_report_summary() -> None:
    report = run_evaluation(event_count=50)

    assert set(report) == {
        "poc1_extraction",
        "llm_extraction",
        "poc2_replay",
        "poc3_affordance",
        "poc4_npc_memory",
        "poc5_quests",
        "three_store_demo_village",
        "summary",
    }
    assert report["summary"]["schema_pass_rate"] == 1.0
    assert report["summary"]["evidence_coverage_rate"] == 1.0
    assert report["summary"]["canonical_error_rate"] == 0.0
    assert report["summary"]["llm_extraction_schema_pass_rate"] == 1.0
    assert report["summary"]["llm_extraction_scope_accuracy"] == 1.0
    assert report["summary"]["llm_extraction_canonical_error_rate"] == 0.0
    assert report["summary"]["replay_accuracy"] == 1.0
    assert report["summary"]["llm_calls_during_replay"] == 0
    assert report["summary"]["illegal_action_block_rate"] == 1.0
    assert report["summary"]["canonical_pollution_rate"] == 0.0
    assert report["summary"]["quest_dependency_valid_rate"] == 1.0
    assert report["summary"]["quest_traceability_rate"] == 1.0
    assert report["summary"]["quest_completable_rate"] == 1.0
    assert report["summary"]["projector_rebuild_consistency"] == 1.0
    assert report["summary"]["kuzu_graph_query_correct"] == 1.0
    assert report["summary"]["chroma_memory_query_correct"] == 1.0
    assert report["summary"]["chroma_scope_leak_rate"] == 0.0
    assert report["summary"]["demo_village_movement_coverage"] >= 1.0
    assert report["summary"]["tension_resolution_rate"] == 1.0
