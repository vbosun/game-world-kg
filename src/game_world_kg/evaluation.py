from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .db import connect, init_db, transaction
from .events import EventLog
from .extraction import ExtractionPipeline
from .projector import StateProjector, delta
from .seed import DEMO_WORLD_ID, seed_demo_world
from .service import GameWorldService


@dataclass
class CountingLLM:
    action_id: str = "talk_to_guard"
    narration: str = "评估旁白。"
    json_calls: int = 0
    text_calls: int = 0

    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0) -> dict[str, Any]:
        self.json_calls += 1
        return {"action_id": self.action_id, "confidence": 0.99, "reason": "evaluation"}

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.4) -> str:
        self.text_calls += 1
        return self.narration

    @property
    def total_calls(self) -> int:
        return self.json_calls + self.text_calls


def run_evaluation(event_count: int = 1000) -> dict[str, Any]:
    poc1 = evaluate_extraction()
    poc2 = evaluate_replay(event_count)
    poc3 = evaluate_affordances()
    poc4 = evaluate_npc_memory()
    return {
        "poc1_extraction": poc1,
        "poc2_replay": poc2,
        "poc3_affordance": poc3,
        "poc4_npc_memory": poc4,
        "summary": {
            "schema_pass_rate": poc1["schema_pass_rate"],
            "evidence_coverage_rate": poc1["evidence_coverage_rate"],
            "canonical_error_rate": poc1["canonical_error_rate"],
            "illegal_or_uncertain_downgrade_rate": poc1["illegal_or_uncertain_downgrade_rate"],
            "replay_accuracy": poc2["replay_accuracy"],
            "llm_calls_during_replay": poc2["llm_calls_during_replay"],
            "illegal_action_block_rate": poc3["illegal_action_block_rate"],
            "action_relevant_rate": poc3["action_relevant_rate"],
            "canonical_pollution_rate": poc4["canonical_pollution_rate"],
            "npc_privileged_knowledge_rate": poc4["npc_privileged_knowledge_rate"],
            "memory_correct_rate": poc4["memory_correct_rate"],
        },
    }


def evaluate_extraction() -> dict[str, Any]:
    service = _new_service()
    pipeline = ExtractionPipeline(service)
    corpus = [
        ("log_001", "玩家把通行令递给守卫。"),
        ("log_002", "村里有人说玩家偷了钥匙。"),
        ("log_003", "守卫怀疑玩家偷了钥匙。"),
        ("log_004", "玩家用并不存在的银钥匙打开铁门。"),
    ]
    results = [pipeline.process_text(source_id, text) for source_id, text in corpus]

    state = service.state(DEMO_WORLD_ID)
    memories = service.memories(DEMO_WORLD_ID)
    checks = [
        state["pass_token"]["holder"] == "guard_alos",
        state["silver_key"]["holder"] == "guard_alos",
        state["iron_gate"]["open"] is False,
        any(memory["truth_scope"] == "rumor" and memory["owner_id"] == "village" for memory in memories),
        any(memory["truth_scope"] == "npc" and memory["owner_id"] == "guard_alos" for memory in memories),
    ]
    downgraded_checks = [
        any(result["candidate"]["scope"] == "rumor" and result["memories"] for result in results),
        any(result["candidate"]["scope"] == "npc" and result["memories"] for result in results),
        any(result["candidate"]["action_id"] == "unlock_gate_with_key" and result["rejected"] for result in results),
    ]
    return {
        "case_count": len(results),
        "schema_pass_rate": _rate([result["schema_pass"] for result in results]),
        "evidence_coverage_rate": _rate([_has_evidence(result) for result in results]),
        "canonical_error_rate": 1.0 - _rate(checks),
        "illegal_or_uncertain_downgrade_rate": _rate(downgraded_checks),
        "results": results,
    }


def evaluate_replay(event_count: int = 1000) -> dict[str, Any]:
    service, llm = _new_service_with_llm()
    _append_reputation_events(service, event_count)

    latest = service.replay(DEMO_WORLD_ID)
    expected_latest = event_count
    latest_ok = latest["state"]["player"]["reputation"] == expected_latest

    midpoint = event_count // 2
    mid = service.replay(DEMO_WORLD_ID, to_turn=midpoint)
    mid_ok = mid["state"]["player"]["reputation"] == midpoint

    calls_before = llm.total_calls
    service.replay(DEMO_WORLD_ID)
    calls_after = llm.total_calls

    checks = [latest_ok, mid_ok, calls_after == calls_before]
    return {
        "event_count": event_count,
        "latest_reputation": latest["state"]["player"]["reputation"],
        "midpoint_turn": midpoint,
        "midpoint_reputation": mid["state"]["player"]["reputation"],
        "replay_accuracy": _rate(checks),
        "llm_calls_during_replay": calls_after - calls_before,
    }


def evaluate_affordances() -> dict[str, Any]:
    service = _new_service()
    checks: list[bool] = []

    initial_ids = _affordance_ids(service)
    checks.append("show_pass_token" in initial_ids)
    checks.append("unlock_gate_with_key" not in initial_ids)
    checks.append("ask_guard_open_gate" not in initial_ids)

    rejected = service.turn(DEMO_WORLD_ID, "我掏出一把并不存在的银钥匙打开铁门")
    checks.append(rejected["accepted"] is False)
    checks.append(service.state(DEMO_WORLD_ID)["iron_gate"]["open"] is False)

    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")
    trusted_ids = _affordance_ids(service)
    checks.append("ask_guard_open_gate" in trusted_ids)

    service.turn(DEMO_WORLD_ID, "请守卫放行让我进去")
    open_ids = _affordance_ids(service)
    checks.append("enter_inner_city" in open_ids)

    illegal_checks = checks[1:5]
    return {
        "case_count": len(checks),
        "passed_cases": sum(1 for item in checks if item),
        "illegal_action_block_rate": _rate(illegal_checks),
        "action_relevant_rate": _rate(checks),
    }


def evaluate_npc_memory() -> dict[str, Any]:
    service = _new_service()
    memory_checks: list[bool] = []
    leak_checks: list[bool] = []
    pollution_checks: list[bool] = []

    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")
    answer = service.npc_dialogue(DEMO_WORLD_ID, "guard_alos", "你记得我做过什么吗")
    memory_checks.append("通行令" in answer["answer"])
    memory_checks.append(any("通行令" in memory["memory_text"] for memory in answer["memories"]))

    service = _new_service()
    service.turn(DEMO_WORLD_ID, "村里有人说玩家偷了钥匙")
    guard_answer = service.npc_dialogue(DEMO_WORLD_ID, "guard_alos", "你知道银钥匙在哪里吗")
    leak_checks.append("guard_alos" not in guard_answer["answer"])
    leak_checks.append("银钥匙在守卫" not in guard_answer["answer"])
    leak_checks.append(guard_answer["memories"] == [])

    village_recall = service.recall_memory(DEMO_WORLD_ID, "village", "玩家偷钥匙")
    guard_recall = service.recall_memory(DEMO_WORLD_ID, "guard_alos", "玩家偷钥匙")
    pollution_checks.append(service.state(DEMO_WORLD_ID)["silver_key"]["holder"] == "guard_alos")
    pollution_checks.append(bool(village_recall and village_recall[0]["truth_scope"] == "rumor"))
    pollution_checks.append(guard_recall == [])

    return {
        "memory_correct_rate": _rate(memory_checks),
        "npc_privileged_knowledge_rate": 1.0 - _rate(leak_checks),
        "canonical_pollution_rate": 1.0 - _rate(pollution_checks),
        "memory_checks": {"passed": sum(1 for item in memory_checks if item), "total": len(memory_checks)},
        "privileged_knowledge_checks": {"passed": sum(1 for item in leak_checks if item), "total": len(leak_checks)},
        "scope_checks": {"passed": sum(1 for item in pollution_checks if item), "total": len(pollution_checks)},
    }


def _new_service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


def _new_service_with_llm() -> tuple[GameWorldService, CountingLLM]:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    llm = CountingLLM()
    return GameWorldService(conn, llm), llm


def _append_reputation_events(service: GameWorldService, event_count: int) -> None:
    with service._lock:
        log = EventLog(service.conn)
        projector = StateProjector(service.conn)
        with transaction(service.conn):
            for index in range(1, event_count + 1):
                turn_id = log.create_turn(DEMO_WORLD_ID, f"evaluation reputation +1 #{index}")
                event = log.append(
                    DEMO_WORLD_ID,
                    turn_id,
                    index,
                    "DELTA_RESOURCE",
                    "system",
                    {"entity_id": "player", "attr": "reputation", "delta": 1},
                    participants=["player"],
                    state_deltas=[delta("player", "reputation", index - 1, index, 1)],
                    evidence_refs=[
                        {
                            "source_id": turn_id,
                            "span": [0, 0],
                            "extractor": "evaluation_poc2",
                            "confidence": 1.0,
                        }
                    ],
                )
                projector.apply_event(event)


def _affordance_ids(service: GameWorldService) -> set[str]:
    return {item["action_id"] for item in service.affordances(DEMO_WORLD_ID)}


def _rate(checks: list[bool]) -> float:
    if not checks:
        return 0.0
    return sum(1 for item in checks if item) / len(checks)


def _has_evidence(result: dict[str, Any]) -> bool:
    evidence = result["candidate"]["evidence"]
    return (
        evidence["source_id"] == result["source_id"]
        and isinstance(evidence["span"], list)
        and len(evidence["span"]) == 2
        and evidence["span"][1] > evidence["span"][0]
        and 0 <= evidence["confidence"] <= 1
    )


if __name__ == "__main__":
    print(json.dumps(run_evaluation(), ensure_ascii=False, indent=2, sort_keys=True))
