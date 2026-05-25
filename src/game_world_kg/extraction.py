from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .affordance import AffordanceEngine
from .db import transaction
from .events import EventLog
from .graph import WorldGraph
from .llm import ALLOWED_ACTION_IDS
from .rules import RuleEngine
from .service import GameWorldService


SCOPES = {"canonical", "player", "npc", "faction", "rumor", "candidate", "rejected"}


@dataclass(frozen=True)
class EvidenceRef:
    source_id: str
    span: tuple[int, int]
    extractor: str
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "span": [self.span[0], self.span[1]],
            "extractor": self.extractor,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ExtractionCandidate:
    source_id: str
    text: str
    action_id: str
    scope: str
    confidence: float
    evidence: EvidenceRef


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    errors: list[str]


class RuleBasedExtractor:
    def extract(self, source_id: str, text: str) -> ExtractionCandidate:
        action_id = RuleEngine.parse_action(text)
        return ExtractionCandidate(
            source_id=source_id,
            text=text,
            action_id=action_id,
            scope=ScopeRouter.route_action(action_id),
            confidence=0.95,
            evidence=EvidenceRef(
                source_id=source_id,
                span=(0, len(text)),
                extractor="rule_based_extractor_v1",
                confidence=0.95,
            ),
        )


class SchemaValidator:
    def validate(self, candidate: ExtractionCandidate) -> ValidationResult:
        errors: list[str] = []
        if candidate.action_id not in ALLOWED_ACTION_IDS:
            errors.append("unknown action_id")
        if candidate.scope not in SCOPES:
            errors.append("unknown scope")
        if not 0 <= candidate.confidence <= 1:
            errors.append("confidence out of range")
        if candidate.evidence.span[0] < 0 or candidate.evidence.span[1] <= candidate.evidence.span[0]:
            errors.append("invalid evidence span")
        if candidate.evidence.source_id != candidate.source_id:
            errors.append("evidence source mismatch")
        return ValidationResult(passed=not errors, errors=errors)


class ScopeRouter:
    @staticmethod
    def route_action(action_id: str) -> str:
        if action_id == "rumor_player_stole_key":
            return "rumor"
        if action_id == "guard_suspects_player":
            return "npc"
        if action_id in {"talk_to_guard"}:
            return "candidate"
        return "canonical"


class ExtractionPipeline:
    def __init__(self, service: GameWorldService) -> None:
        self.service = service
        self.extractor = RuleBasedExtractor()
        self.validator = SchemaValidator()

    def process_text(self, source_id: str, text: str) -> dict[str, Any]:
        candidate = self.extractor.extract(source_id, text)
        validation = self.validator.validate(candidate)
        if not validation.passed:
            return {
                "source_id": source_id,
                "text": text,
                "candidate": _candidate_payload(candidate),
                "schema_pass": False,
                "validation_errors": validation.errors,
                "accepted": False,
                "events": [],
                "memories": [],
                "rejected": [{"reason": "schema validation failed"}],
                "affordances": self.service.affordances(self._world_id),
            }
        return self._apply_candidate(candidate)

    @property
    def _world_id(self) -> str:
        from .seed import DEMO_WORLD_ID

        return DEMO_WORLD_ID

    def _apply_candidate(self, candidate: ExtractionCandidate) -> dict[str, Any]:
        with self.service._lock:
            self.service._require_world(self._world_id)
            before_memory_ids = {memory["id"] for memory in WorldGraph(self.service.conn).memories(self._world_id)}
            with transaction(self.service.conn):
                log = EventLog(self.service.conn)
                turn_id = log.create_turn(self._world_id, candidate.text)
                turn = self.service.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
                result = RuleEngine(self.service.conn).resolve_turn(
                    self._world_id,
                    turn_id,
                    turn["turn_index"],
                    candidate.text,
                    action_id=candidate.action_id,
                    extractor=candidate.evidence.extractor,
                    confidence=candidate.confidence,
                    evidence_source_id=candidate.source_id,
                )
                self.service.conn.execute("UPDATE turns SET narration = ? WHERE id = ?", (result.narration, turn_id))
            events = [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "actor_id": event.actor_id,
                    "participants": event.participants,
                    "payload": event.payload,
                    "evidence_refs": event.evidence_refs,
                }
                for event in result.events
            ]
            memories = [
                memory
                for memory in WorldGraph(self.service.conn).memories(self._world_id)
                if memory["id"] not in before_memory_ids
            ]
            rejected = [] if result.accepted else [{"action_id": candidate.action_id, "reason": result.reason}]
            return {
                "source_id": candidate.source_id,
                "text": candidate.text,
                "candidate": _candidate_payload(candidate),
                "schema_pass": True,
                "validation_errors": [],
                "accepted": result.accepted,
                "rule_reason": result.reason,
                "events": events,
                "memories": memories,
                "rejected": rejected,
                "affordances": AffordanceEngine(self.service.conn).list_for_player(self._world_id),
            }


def _candidate_payload(candidate: ExtractionCandidate) -> dict[str, Any]:
    return {
        "action_id": candidate.action_id,
        "scope": candidate.scope,
        "confidence": candidate.confidence,
        "evidence": candidate.evidence.as_dict(),
    }
