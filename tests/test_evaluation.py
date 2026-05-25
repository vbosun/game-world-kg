from __future__ import annotations

from game_world_kg.evaluation import evaluate_affordances, evaluate_npc_memory, evaluate_replay, run_evaluation


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


def test_run_evaluation_returns_report_summary() -> None:
    report = run_evaluation(event_count=50)

    assert set(report) == {"poc2_replay", "poc3_affordance", "poc4_npc_memory", "summary"}
    assert report["summary"]["replay_accuracy"] == 1.0
    assert report["summary"]["llm_calls_during_replay"] == 0
    assert report["summary"]["illegal_action_block_rate"] == 1.0
    assert report["summary"]["canonical_pollution_rate"] == 0.0
