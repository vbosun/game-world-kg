from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .db import to_json, utc_now
from .events import EventLog, EventRecord
from .projector import StateProjector


@dataclass(frozen=True)
class DialogueSegment:
    id: str
    text: str
    speaker_id: str
    span: tuple[int, int]
    segment_kind: str = "dialogue_edu"


@dataclass(frozen=True)
class MemoryOp:
    op_type: str
    layer: str
    owner_id: str
    scope_key: str
    claim_key: str
    memory_text: str
    confidence: float
    segment_id: str
    evidence_refs: list[dict[str, Any]]
    payload: dict[str, Any]


class DialogueMemoryPipeline:
    """Turns immutable NPC dialogue evidence into governed memory operations."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def process_npc_dialogue(
        self,
        *,
        world_id: str,
        turn_id: str,
        turn_index: int,
        dialogue_event: EventRecord,
        npc_id: str,
        question: str,
        answer: str,
        recalled_memory_ids: list[str],
    ) -> dict[str, Any]:
        source_text = f"player: {question}\n{npc_id}: {answer}"
        source_id = self._append_source_text(world_id, turn_id, source_text)
        segments = self._segment_dialogue(world_id, turn_id, dialogue_event.id, source_text, npc_id, question, answer)
        for index, segment in enumerate(segments):
            self._append_segment(world_id, turn_id, dialogue_event.id, index, segment)
        ops = self._build_ops(
            dialogue_event=dialogue_event,
            source_id=source_id,
            npc_id=npc_id,
            question=question,
            answer=answer,
            recalled_memory_ids=recalled_memory_ids,
            segments=segments,
        )
        stored_ops = [self._store_op(world_id, dialogue_event.id, op) for op in ops]
        applied_events: list[EventRecord] = []
        review_items: list[dict[str, Any]] = []
        for op_id, op in zip(stored_ops, ops):
            validation = self._validate_op(op)
            if validation is not None:
                review_items.append(self._append_review(world_id, dialogue_event.id, op_id, validation, op))
                self._mark_op(op_id, "review", reason=validation)
                continue
            event = self._apply_op(world_id, turn_id, turn_index, dialogue_event, op)
            self._mark_op(op_id, "applied", applied_event_id=event.id)
            applied_events.append(event)
        return {
            "source_id": source_id,
            "segments": [_segment_payload(segment) for segment in segments],
            "memory_ops": self.memory_ops(world_id, dialogue_event.id),
            "review_items": review_items,
            "applied_event_ids": [event.id for event in applied_events],
        }

    def memory_ops(self, world_id: str, source_event_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [world_id]
        where = "world_id = ?"
        if source_event_id is not None:
            where += " AND source_event_id = ?"
            params.append(source_event_id)
        return [
            {
                "id": row["id"],
                "source_event_id": row["source_event_id"],
                "segment_id": row["segment_id"],
                "op_type": row["op_type"],
                "layer": row["layer"],
                "owner_id": row["owner_id"],
                "scope_key": row["scope_key"],
                "claim_key": row["claim_key"],
                "memory_text": row["memory_text"],
                "payload": _from_json_row(row["payload_json"]),
                "confidence": row["confidence"],
                "status": row["status"],
                "applied_event_id": row["applied_event_id"],
                "reason": row["reason"],
            }
            for row in self.conn.execute(f"SELECT * FROM memory_ops WHERE {where} ORDER BY created_at", params).fetchall()
        ]

    def review_items(self, world_id: str, status: str = "open") -> list[dict[str, Any]]:
        return [
            {
                "id": row["id"],
                "source_event_id": row["source_event_id"],
                "memory_op_id": row["memory_op_id"],
                "reason": row["reason"],
                "payload": _from_json_row(row["payload_json"]),
                "status": row["status"],
            }
            for row in self.conn.execute(
                "SELECT * FROM review_queue WHERE world_id = ? AND status = ? ORDER BY created_at",
                (world_id, status),
            ).fetchall()
        ]

    def _append_source_text(self, world_id: str, turn_id: str, text: str) -> str:
        source_id = f"src_{uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO source_texts(id, world_id, source_type, text, turn_id, created_at)
            VALUES (?, ?, 'npc_dialogue', ?, ?, ?)
            """,
            (source_id, world_id, text, turn_id, utc_now()),
        )
        return source_id

    def _segment_dialogue(
        self,
        world_id: str,
        turn_id: str,
        source_event_id: str,
        source_text: str,
        npc_id: str,
        question: str,
        answer: str,
    ) -> list[DialogueSegment]:
        player_text = f"player: {question}"
        npc_text = f"{npc_id}: {answer}"
        npc_start = len(player_text) + 1
        return [
            DialogueSegment(
                id=f"seg_{uuid4().hex}",
                text=question,
                speaker_id="player",
                span=(len("player: "), len(player_text)),
            ),
            DialogueSegment(
                id=f"seg_{uuid4().hex}",
                text=answer,
                speaker_id=npc_id,
                span=(npc_start + len(f"{npc_id}: "), len(source_text)),
            ),
        ]

    def _append_segment(self, world_id: str, turn_id: str, source_event_id: str, index: int, segment: DialogueSegment) -> None:
        self.conn.execute(
            """
            INSERT INTO conversation_segments(
                id, world_id, turn_id, source_event_id, speaker_id, segment_index,
                segment_kind, text, span_start, span_end, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment.id,
                world_id,
                turn_id,
                source_event_id,
                segment.speaker_id,
                index,
                segment.segment_kind,
                segment.text,
                segment.span[0],
                segment.span[1],
                utc_now(),
            ),
        )

    def _build_ops(
        self,
        *,
        dialogue_event: EventRecord,
        source_id: str,
        npc_id: str,
        question: str,
        answer: str,
        recalled_memory_ids: list[str],
        segments: list[DialogueSegment],
    ) -> list[MemoryOp]:
        question_segment = segments[0]
        evidence = [
            {
                "source_id": source_id,
                "source_type": "npc_dialogue",
                "span": [question_segment.span[0], question_segment.span[1]],
                "text": question,
                "extractor": "dialogue_memory_pipeline_v1",
                "confidence": 1.0,
            }
        ]
        ops = [
            MemoryOp(
                op_type="ADD_MEMORY",
                layer="episodic",
                owner_id=npc_id,
                scope_key=f"npc_belief:{npc_id}",
                claim_key=f"dialogue_question:{dialogue_event.id}",
                memory_text=_dialogue_episode_text(question, bool(recalled_memory_ids)),
                confidence=1.0,
                segment_id=question_segment.id,
                evidence_refs=evidence,
                payload={
                    "memory_kind": "dialogue_episode",
                    "supporting_memory_ids": recalled_memory_ids,
                    "source_event_id": dialogue_event.id,
                },
            )
        ]
        rumor_text = _rumor_claim(question, answer)
        if rumor_text is not None:
            ops.append(
                MemoryOp(
                    op_type="FLAG_RUMOR",
                    layer="belief",
                    owner_id=npc_id,
                    scope_key="rumor:village_square",
                    claim_key=f"rumor:{_claim_slug(rumor_text)}",
                    memory_text=rumor_text,
                    confidence=0.55,
                    segment_id=question_segment.id,
                    evidence_refs=evidence,
                    payload={
                        "memory_kind": "rumor_claim",
                        "source_event_id": dialogue_event.id,
                    },
                )
            )
        return ops

    def _store_op(self, world_id: str, source_event_id: str, op: MemoryOp) -> str:
        op_id = f"mop_{uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO memory_ops(
                id, world_id, source_event_id, segment_id, op_type, layer, owner_id,
                scope_key, claim_key, memory_text, payload_json, confidence, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
            """,
            (
                op_id,
                world_id,
                source_event_id,
                op.segment_id,
                op.op_type,
                op.layer,
                op.owner_id,
                op.scope_key,
                op.claim_key,
                op.memory_text,
                to_json(op.payload),
                op.confidence,
                utc_now(),
            ),
        )
        return op_id

    def _validate_op(self, op: MemoryOp) -> str | None:
        if not op.evidence_refs:
            return "missing_evidence"
        if op.scope_key == "canonical" or op.layer == "canonical":
            return "dialogue_cannot_write_canonical"
        if op.op_type not in {"ADD_MEMORY", "FLAG_RUMOR", "CORRECT_MEMORY", "MERGE_MEMORY", "UPDATE_MEMORY"}:
            return "unknown_memory_op"
        return None

    def _apply_op(
        self,
        world_id: str,
        turn_id: str,
        turn_index: int,
        dialogue_event: EventRecord,
        op: MemoryOp,
    ) -> EventRecord:
        truth_scope = _truth_scope_from_key(op.scope_key)
        event = EventLog(self.conn).append(
            world_id,
            turn_id,
            turn_index,
            "ADD_MEMORY",
            "system",
            {
                "owner_id": op.owner_id,
                "source_event_id": dialogue_event.id,
                "memory_text": op.memory_text,
                "truth_scope": truth_scope,
                "scope_key": op.scope_key,
                "layer": op.layer,
                "memory_kind": op.payload.get("memory_kind", "dialogue_episode"),
                "supporting_memory_ids": op.payload.get("supporting_memory_ids", []),
                "salience": 0.35 if op.op_type == "ADD_MEMORY" else 0.55,
                "valence": 0,
                "confidence": op.confidence,
            },
            participants=[op.owner_id, "player"],
            evidence_refs=op.evidence_refs,
            causal_parents=[dialogue_event.id],
        )
        StateProjector(self.conn).apply_event(event)
        return event

    def _append_review(self, world_id: str, source_event_id: str, op_id: str, reason: str, op: MemoryOp) -> dict[str, Any]:
        review_id = f"rev_{uuid4().hex}"
        payload = _op_payload(op)
        self.conn.execute(
            """
            INSERT INTO review_queue(
                id, world_id, source_event_id, memory_op_id, reason, payload_json, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (review_id, world_id, source_event_id, op_id, reason, to_json(payload), utc_now()),
        )
        return {"id": review_id, "memory_op_id": op_id, "reason": reason, "payload": payload, "status": "open"}

    def _mark_op(self, op_id: str, status: str, *, applied_event_id: str | None = None, reason: str | None = None) -> None:
        self.conn.execute(
            """
            UPDATE memory_ops
            SET status = ?, applied_event_id = ?, reason = ?, applied_at = ?
            WHERE id = ?
            """,
            (status, applied_event_id, reason, utc_now() if status == "applied" else None, op_id),
        )


def _dialogue_episode_text(question: str, had_supporting_memory: bool, limit: int = 240) -> str:
    text = f"玩家曾向我询问：{question}"
    if had_supporting_memory:
        text += "；我当时依据已有记忆作答。"
    return text if len(text) <= limit else f"{text[: limit - 1]}..."


def _rumor_claim(question: str, answer: str) -> str | None:
    text = f"{question} {answer}"
    if not any(marker in text for marker in ["听说", "传言", "谣言", "有人说"]):
        return None
    sentence = re.split(r"[。！？!?]", text.strip())[0]
    return sentence[:160] if sentence else None


def _claim_slug(text: str) -> str:
    return re.sub(r"\W+", "_", text, flags=re.UNICODE).strip("_")[:48] or "claim"


def _truth_scope_from_key(scope_key: str) -> str:
    if scope_key.startswith("npc_belief:"):
        return "npc"
    if scope_key.startswith("rumor:"):
        return "rumor"
    if scope_key == "semantic_shared":
        return "faction"
    return scope_key


def _segment_payload(segment: DialogueSegment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "speaker_id": segment.speaker_id,
        "segment_kind": segment.segment_kind,
        "text": segment.text,
        "span": [segment.span[0], segment.span[1]],
    }


def _op_payload(op: MemoryOp) -> dict[str, Any]:
    return {
        "op_type": op.op_type,
        "layer": op.layer,
        "owner_id": op.owner_id,
        "scope_key": op.scope_key,
        "claim_key": op.claim_key,
        "memory_text": op.memory_text,
        "confidence": op.confidence,
        "evidence_refs": op.evidence_refs,
        "payload": op.payload,
    }


def _from_json_row(value: str) -> Any:
    import json

    return json.loads(value)
