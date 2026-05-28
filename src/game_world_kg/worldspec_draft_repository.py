from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from .db import to_json, utc_now


class RawDraftRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(
        self,
        *,
        trace_id: str | None,
        idea: str,
        provider: str | None,
        model: str | None,
        raw_text: str,
        extracted_json_text: str | None = None,
        json_parse_status: str = "pending",
        json_parse_error: str | None = None,
        status: str = "created",
    ) -> str:
        raw_id = f"raw_{uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO worldspec_raw_drafts(
                raw_id, trace_id, idea, provider, model, raw_text,
                extracted_json_text, json_parse_status, json_parse_error, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (raw_id, trace_id, idea, provider, model, raw_text, extracted_json_text, json_parse_status, json_parse_error, status, utc_now()),
        )
        return raw_id

    def get(self, raw_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM worldspec_raw_drafts WHERE raw_id = ?", (raw_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def latest(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM worldspec_raw_drafts ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return dict(row)

    def update_parse_result(self, raw_id: str, *, extracted_json_text: str, json_parse_status: str, json_parse_error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE worldspec_raw_drafts SET extracted_json_text = ?, json_parse_status = ?, json_parse_error = ? WHERE raw_id = ?",
            (extracted_json_text, json_parse_status, json_parse_error, raw_id),
        )


class CandidateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, *, raw_id: str, trace_id: str | None, world_id: str, spec_json: dict[str, Any], status: str = "pending", validation_report_json: dict[str, Any] | None = None) -> str:
        candidate_id = f"cand_{uuid4().hex}"
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO worldspec_candidates(
                candidate_id, raw_id, trace_id, world_id, spec_json,
                status, validation_report_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (candidate_id, raw_id, trace_id, world_id, to_json(spec_json), status, to_json(validation_report_json or {}), now, now),
        )
        return candidate_id

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM worldspec_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_by_raw(self, raw_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM worldspec_candidates WHERE raw_id = ? ORDER BY created_at DESC", (raw_id,)).fetchall()
        return [dict(row) for row in rows]

    def update_validation(self, candidate_id: str, validation_report_json: dict[str, Any], status: str | None = None) -> None:
        params: list[Any] = [to_json(validation_report_json), utc_now()]
        sets = "validation_report_json = ?, updated_at = ?"
        if status is not None:
            sets += ", status = ?"
            params.append(status)
        params.append(candidate_id)
        self.conn.execute(f"UPDATE worldspec_candidates SET {sets} WHERE candidate_id = ?", params)

    def submit_repaired_json(self, candidate_id: str, spec_json: dict[str, Any], validation_report_json: dict[str, Any] | None = None) -> None:
        import hashlib, json as _json
        # Record current version in patch history before overwriting
        current = self.get(candidate_id)
        if current is not None:
            old_spec = current.get("spec_json")
            old_spec_str = old_spec if isinstance(old_spec, str) else to_json(old_spec or {})
            old_spec_obj = old_spec if isinstance(old_spec, dict) else (_json.loads(old_spec_str) if isinstance(old_spec_str, str) and old_spec_str else {})
            old_hash = hashlib.sha256(
                _json.dumps(old_spec_obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            old_report = current.get("validation_report_json") or "{}"
            old_report_str = old_report if isinstance(old_report, str) else to_json(old_report)
            # Get next version number
            max_ver = self.conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM candidate_patch_history WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()[0]
            self.conn.execute(
                """
                INSERT INTO candidate_patch_history(id, candidate_id, version, spec_json, spec_hash, validation_report_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"patch_{uuid4().hex}", candidate_id, max_ver + 1, old_spec_str, old_hash, old_report_str, utc_now()),
            )
        if validation_report_json is not None:
            self.conn.execute(
                "UPDATE worldspec_candidates SET spec_json = ?, validation_report_json = ?, updated_at = ? WHERE candidate_id = ?",
                (to_json(spec_json), to_json(validation_report_json), utc_now(), candidate_id),
            )
        else:
            self.conn.execute(
                "UPDATE worldspec_candidates SET spec_json = ?, updated_at = ? WHERE candidate_id = ?",
                (to_json(spec_json), utc_now(), candidate_id),
            )

    def patch_history(self, candidate_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM candidate_patch_history WHERE candidate_id = ? ORDER BY version DESC",
            (candidate_id,),
        ).fetchall()
        return [dict(row) for row in rows]
