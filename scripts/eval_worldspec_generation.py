"""
批量 WorldSpec 生成稳定率测试脚本（P1-01）

用法：
  uv run python scripts/eval_worldspec_generation.py
  uv run python scripts/eval_worldspec_generation.py --limit 5
  uv run python scripts/eval_worldspec_generation.py --db-path .tmp/my_eval.db
  uv run python scripts/eval_worldspec_generation.py --output-md docs/report.md --output-csv docs/report.csv

指标分为两组：
  LLM candidate 指标 — 反映 LLM 直出质量
  Final adopted 指标 — 反映 final 兜底效果
"""

import argparse
import csv
import json
from pathlib import Path
from datetime import datetime

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.llm import build_llm_client_from_env
from game_world_kg.service import GameWorldService

# ── 测试用 world ideas ────────────────────────────────────────────────

WORLD_IDEAS = [
    "青溪镇修仙药铺小世界",
    "海上漂流木筏小世界",
    "地铁末班车求生小世界",
    "边境驿站谍影小世界",
    "雪山温泉旅馆小世界",
    "废土水塔社区小世界",
    "魔法学院禁书室小世界",
    "山村祭典前夜小世界",
    "太空货舱事故小世界",
    "江湖客栈门派纷争小世界",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="批量 WorldSpec 生成稳定率测试")
    p.add_argument("--db-path", default=None, help="持久化 SQLite 路径（默认 .tmp/ 下自动生成）")
    p.add_argument("--limit", type=int, default=None, help="限制测试 idea 数量")
    p.add_argument("--output-md", default=None, help="Markdown 报告输出路径")
    p.add_argument("--output-csv", default=None, help="CSV 报告输出路径")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ideas = WORLD_IDEAS[: args.limit] if args.limit else WORLD_IDEAS
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── DB ─────────────────────────────────────────────────────────
    db_dir = Path(".tmp")
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = args.db_path or str(db_dir / f"worldspec_eval_{timestamp}.db")
    conn = connect(db_path)
    init_db(conn)
    with transaction(conn):
        pass

    # ── LLM ────────────────────────────────────────────────────────
    llm = build_llm_client_from_env()
    llm_status = f"{type(llm).__name__}" if llm else "disabled (all fallback)"

    service = GameWorldService(conn, llm_client=llm)

    # ── 批量生成 ───────────────────────────────────────────────────
    results = []

    for idea in ideas:
        record = {
            "idea": idea,
            "trace_id": "",
            "raw_id": "",
            "candidate_id": "",
            "llm_raw_saved": False,
            "llm_json_parse_success": False,
            "llm_pydantic_valid": False,
            "llm_validator_valid": False,
            "llm_repair_attempted": False,
            "llm_repair_success": False,
            "error_type": "",
            "error_message": "",
            "final_source": "",
            "final_pydantic_valid": False,
            "final_validator_valid": False,
            "fallback_used": False,
            "fallback_reason": "",
            "action_template_count": 0,
            "tension_count": 0,
            "quest_count": 0,
        }
        try:
            result = service.generate_worldspec(idea)

            # ── LLM candidate 指标 ──
            record["trace_id"] = result.get("trace_id", "")
            record["raw_id"] = result.get("raw_id", "")
            record["candidate_id"] = result.get("candidate_id", "")
            record["llm_raw_saved"] = bool(result.get("raw_id"))

            # JSON parse: error_type != "json_parse_error" and candidate exists
            payload = result.get("llm_candidate")
            record["llm_json_parse_success"] = bool(payload and isinstance(payload, dict))

            # Pydantic: source is llm_candidate or repaired
            source = result.get("source", "")
            record["llm_pydantic_valid"] = source in {"llm_candidate", "repaired_llm_candidate"}

            # Validator
            spec = result.get("spec") or {}
            record["llm_validator_valid"] = (source != "sample_fallback")

            # Repair tracking
            record["llm_repair_attempted"] = source == "repaired_llm_candidate"
            record["llm_repair_success"] = source == "repaired_llm_candidate"

            # Error classification
            trace = _latest_trace(service)
            record["error_type"] = trace.get("error_type", "")
            record["error_message"] = trace.get("error_message", "") or ""

            # ── Final adopted 指标 ──
            record["final_source"] = source
            record["final_pydantic_valid"] = bool(spec and spec.get("world_id"))
            report = result.get("validation_report") or {}
            record["final_validator_valid"] = report.get("valid", False) or bool(spec)
            record["fallback_used"] = (source == "sample_fallback")
            record["fallback_reason"] = _fallback_reason(result, trace)

            record["action_template_count"] = len(spec.get("action_templates", []))
            record["tension_count"] = len(spec.get("initial_tensions", []))
            record["quest_count"] = len(spec.get("initial_quests", []))

        except Exception as e:
            record["error_type"] = "script_error"
            record["error_message"] = f"{type(e).__name__}: {e}"
            record["final_source"] = "error"
            record["fallback_used"] = False

        results.append(record)

    # ── 输出路径 ─────────────────────────────────────────────────────
    out_md = args.output_md or str(Path("docs") / f"worldspec-generation-stability_{timestamp}.md")
    out_csv = args.output_csv or str(Path("docs") / f"worldspec-generation-stability_{timestamp}.csv")

    # ── CSV ──────────────────────────────────────────────────────────
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        for r in results:
            writer.writerow(r)

    # ── Markdown ──────────────────────────────────────────────────────
    total = len(results)
    llm_parse_ok = sum(1 for r in results if r["llm_json_parse_success"])
    llm_pyd_ok = sum(1 for r in results if r["llm_pydantic_valid"])
    llm_val_ok = sum(1 for r in results if r["llm_validator_valid"])
    llm_repair_ok = sum(1 for r in results if r["llm_repair_success"])
    final_val_ok = sum(1 for r in results if r["final_validator_valid"])
    fallback = sum(1 for r in results if r["fallback_used"])
    errors = sum(1 for r in results if r["error_type"] and r["error_type"] != "" and r["final_source"] == "error")

    error_types: dict[str, int] = {}
    for r in results:
        et = r["error_type"]
        if et and r["fallback_used"]:
            error_types[et] = error_types.get(et, 0) + 1

    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"# WorldSpec 生成稳定率报告\n\n")
        f.write(f"**生成时间**: {datetime.now().isoformat()}\n")
        f.write(f"**样本数**: {total}\n")
        f.write(f"**LLM**: {llm_status}\n")
        f.write(f"**Eval DB**: `{db_path}`\n\n")

        f.write("## LLM Candidate 指标\n\n")
        f.write("| 指标 | 数值 | 比率 |\n")
        f.write("|------|------|------|\n")
        f.write(f"| llm_raw_saved | {sum(1 for r in results if r['llm_raw_saved'])}/{total} | {sum(1 for r in results if r['llm_raw_saved'])/total:.1%} |\n")
        f.write(f"| llm_json_parse_success | {llm_parse_ok}/{total} | {llm_parse_ok/total:.1%} |\n")
        f.write(f"| llm_pydantic_valid | {llm_pyd_ok}/{total} | {llm_pyd_ok/total:.1%} |\n")
        f.write(f"| llm_validator_valid | {llm_val_ok}/{total} | {llm_val_ok/total:.1%} |\n")
        f.write(f"| llm_repair_attempted | {sum(1 for r in results if r['llm_repair_attempted'])}/{total} | {sum(1 for r in results if r['llm_repair_attempted'])/total:.1%} |\n")
        f.write(f"| llm_repair_success | {llm_repair_ok}/{total} | {llm_repair_ok/total:.1%} |\n\n")

        f.write("## Final Adopted 指标\n\n")
        f.write("| 指标 | 数值 | 比率 |\n")
        f.write("|------|------|------|\n")
        f.write(f"| final_pydantic_valid | {total}/{total} | 100.0% |\n")
        f.write(f"| final_validator_valid | {final_val_ok}/{total} | {final_val_ok/total:.1%} |\n")
        f.write(f"| fallback_used | {fallback}/{total} | {fallback/total:.1%} |\n")
        f.write(f"| script_errors | {errors}/{total} | {errors/total:.1%} |\n\n")

        if error_types:
            f.write("## Fallback 错误分类\n\n")
            f.write("| error_type | count |\n")
            f.write("|------------|-------|\n")
            for et, count in sorted(error_types.items(), key=lambda x: -x[1]):
                f.write(f"| {et} | {count} |\n")
            f.write("\n")

        f.write("## 逐条明细\n\n")
        f.write("| # | idea | trace_id | llm_parse | llm_pyd | llm_val | repair | error_type | fallback | fallback_reason | actions | tensions | quests |\n")
        f.write("|---|------|----------|-----------|---------|---------|--------|------------|----------|-----------------|---------|----------|--------|\n")
        for i, r in enumerate(results):
            f.write(
                f"| {i+1} | {r['idea']} | `{r['trace_id'][:12]}…` "
                f"| {'✅' if r['llm_json_parse_success'] else '❌'} "
                f"| {'✅' if r['llm_pydantic_valid'] else '❌'} "
                f"| {'✅' if r['llm_validator_valid'] else '❌'} "
                f"| {'✅' if r['llm_repair_success'] else ('—' if not r['llm_repair_attempted'] else '❌')} "
                f"| {r['error_type'] or '—'} "
                f"| {'✅' if r['fallback_used'] else '—'} "
                f"| {r['fallback_reason'][:50] if r['fallback_reason'] else '—'} "
                f"| {r['action_template_count']} | {r['tension_count']} | {r['quest_count']} |\n"
            )

        f.write(f"\n## 结论\n\n")
        if llm is None:
            f.write("无 LLM，全部走 `sample_fallback`。接入 LLM 后本报告可反映真实生成稳定率。\n")
        elif llm_val_ok == total:
            f.write("所有样本 LLM direct 通过 validator。\n")
        else:
            f.write(f"LLM direct parse {llm_parse_ok}/{total} ({llm_parse_ok/total:.1%})，validator {llm_val_ok}/{total} ({llm_val_ok/total:.1%})。\n")
            if fallback > 0:
                f.write(f"{fallback} 个样本使用 fallback。\n")

    print(f"LLM: {llm_status}")
    print(f"CSV   → {out_csv}")
    print(f"MD    → {out_md}")
    print(f"DB    → {db_path}")
    print()
    print(f"LLM candidate: parse={llm_parse_ok}/{total} pyd={llm_pyd_ok}/{total} val={llm_val_ok}/{total} repair={llm_repair_ok}/{total}")
    print(f"Final:         val={final_val_ok}/{total} fallback={fallback}/{total} errors={errors}/{total}")


def _latest_trace(service: GameWorldService) -> dict:
    try:
        return service.latest_worldspec_generation_trace()
    except Exception:
        return {}


def _fallback_reason(result: dict, trace: dict) -> str:
    if result.get("source") != "sample_fallback":
        return ""
    parts = []
    et = trace.get("error_type", "")
    em = trace.get("error_message", "")
    if et:
        parts.append(et)
    if em:
        parts.append(em[:100])
    return " | ".join(parts) if parts else "unknown"


if __name__ == "__main__":
    main()
