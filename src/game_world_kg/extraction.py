from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .affordance import AffordanceEngine
from .db import transaction
from .events import EventLog
from .graph import WorldGraph
from .llm import ALLOWED_ACTION_IDS, LLMClient, LLMError
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


class LLMExtractor:
    def __init__(self, client: LLMClient | None) -> None:
        self.client = client

    def extract(
        self,
        source_id: str,
        text: str,
        state_summary: dict[str, Any],
        known_entities: list[dict[str, Any]],
    ) -> ExtractionCandidate | None:
        if self.client is None:
            return None
        messages = [
            {
                "role": "system",
                "content": (
                    "你是游戏世界日志抽取器。只输出 JSON 对象，不要解释。"
                    f"action_id 只能是: {', '.join(sorted(ALLOWED_ACTION_IDS))}。"
                    "这是旧日志抽取 PoC 路径，只能使用上述固定 action_id；不要发明动态 WorldSpec action_id。"
                    "根据文本提出候选 action_id、confidence、evidence_span。"
                    "不要决定是否进入 canonical，系统会用本地 ScopeRouter 和 RuleEngine 裁判。"
                    "格式: {\"action_id\":\"...\",\"confidence\":0.0,\"evidence_span\":[0,1]}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"source_id={source_id}\n"
                    f"text={text}\n"
                    f"state_summary={state_summary}\n"
                    f"known_entities={known_entities}"
                ),
            },
        ]
        try:
            raw = self.client.complete_json(messages, temperature=0)
        except LLMError:
            return None
        action_id = raw.get("action_id")
        if action_id not in ALLOWED_ACTION_IDS:
            return None
        confidence = _coerce_confidence(raw.get("confidence", 0.5))
        span = _coerce_span(raw.get("evidence_span"), len(text))
        return ExtractionCandidate(
            source_id=source_id,
            text=text,
            action_id=action_id,
            scope=ScopeRouter.route_action(action_id),
            confidence=confidence,
            evidence=EvidenceRef(
                source_id=source_id,
                span=span,
                extractor="llm_extractor_v1",
                confidence=confidence,
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
        self.llm_extractor = LLMExtractor(service.llm_client)
        self.validator = SchemaValidator()

    def process_text(self, source_id: str, text: str) -> dict[str, Any]:
        candidate = self.extractor.extract(source_id, text)
        if candidate.action_id == "talk_to_guard" and self.service.llm_client is not None:
            llm_candidate = self.llm_extractor.extract(
                source_id,
                text,
                self.service.state(self._world_id),
                self.service.graph(self._world_id)["nodes"],
            )
            if llm_candidate is not None:
                candidate = llm_candidate
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
                    evidence_span=[candidate.evidence.span[0], candidate.evidence.span[1]],
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


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, confidence))


def _coerce_span(value: Any, text_length: int) -> tuple[int, int]:
    if isinstance(value, list) and len(value) == 2:
        try:
            start = int(value[0])
            end = int(value[1])
        except (TypeError, ValueError):
            return (0, text_length)
        start = max(0, min(start, text_length))
        end = max(start + 1, min(end, text_length))
        if text_length > 1 and end - start <= 1:
            return (0, text_length)
        return (start, end)
    return (0, text_length)
