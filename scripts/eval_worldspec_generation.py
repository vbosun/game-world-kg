"""
批量 WorldSpec 生成稳定率测试脚本（P1-01）
统计 raw_saved / json_parse_success / pydantic_valid / validator_valid / fallback_rate / repair_used

用法：
  uv run python scripts/eval_worldspec_generation.py

无 LLM 时所有 idea 走 sample_fallback，脚本仍然正常统计。
"""

import csv
import json
from pathlib import Path
from datetime import datetime

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.llm import build_llm_client_from_env
from game_world_kg.service import GameWorldService

# ── 初始化 LLM ─────────────────────────────────────────────────────────

llm = build_llm_client_from_env()
if llm:
    print(f"LLM: {type(llm).__name__} enabled")
else:
    print("LLM: disabled (all samples will use fallback)")

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

OUTPUT_DIR = Path("docs")
OUTPUT_PREFIX = f"worldspec-generation-stability_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ── 初始化服务 ─────────────────────────────────────────────────────────

conn = connect(":memory:")
init_db(conn)
with transaction(conn):
    pass  # 确保 db schema 就绪
service = GameWorldService(conn, llm_client=llm)

# ── 批量生成 ───────────────────────────────────────────────────────────

results = []

for idea in WORLD_IDEAS:
    record = {
        "idea": idea,
        "trace_id": "",
        "raw_id": "",
        "candidate_id": "",
        "source": "",
        "raw_saved": False,
        "json_parse_success": False,
        "pydantic_valid": False,
        "validator_valid": False,
        "repair_used": False,
        "fallback_used": False,
        "action_template_count": 0,
        "tension_count": 0,
        "quest_count": 0,
        "main_error": "",
    }
    try:
        result = service.generate_worldspec(idea)

        # 从返回 dict 提取字段
        record["trace_id"] = result.get("trace_id", "")
        record["raw_id"] = result.get("raw_id", "")
        record["candidate_id"] = result.get("candidate_id", "")
        record["source"] = result.get("source", "")

        # raw_saved: raw_id 非空即 raw draft 已保存到 DB
        record["raw_saved"] = bool(result.get("raw_id"))

        # source 判断
        record["fallback_used"] = (result.get("source") == "sample_fallback")

        # json_parse_success: 有 generation_error 则为 False（LLM JSON parse 失败）
        gen_error = result.get("generation_error")
        record["json_parse_success"] = not bool(gen_error)

        # validation_report
        report = result.get("validation_report") or {}
        record["validator_valid"] = report.get("valid", False)

        # pydantic_valid: 有 spec 且 world_id 非空（Pydantic model_validate 成功）
        spec = result.get("spec") or {}
        record["pydantic_valid"] = bool(spec and spec.get("world_id"))

        # repair: 有 repair_attempts 且 > 1 说明用过 repair
        repair_attempts = result.get("repair_attempts") or []
        record["repair_used"] = len(repair_attempts) > 1

        # 规格统计
        record["action_template_count"] = len(spec.get("action_templates", []))
        record["tension_count"] = len(spec.get("initial_tensions", []))
        record["quest_count"] = len(spec.get("initial_quests", []))

    except Exception as e:
        record["main_error"] = f"{type(e).__name__}: {e}"

    results.append(record)

# ── 输出 CSV ───────────────────────────────────────────────────────────

csv_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}.csv"
csv_path.parent.mkdir(parents=True, exist_ok=True)
with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
    writer.writeheader()
    for r in results:
        writer.writerow(r)

# ── 输出 Markdown 报告 ─────────────────────────────────────────────────

total = len(results)
raw_count = sum(1 for r in results if r["raw_saved"])
json_ok = sum(1 for r in results if r["json_parse_success"])
pydantic_ok = sum(1 for r in results if r["pydantic_valid"])
validator_ok = sum(1 for r in results if r["validator_valid"])
fallback_count = sum(1 for r in results if r["fallback_used"])
repair_count = sum(1 for r in results if r["repair_used"])
error_count = sum(1 for r in results if r["main_error"])

md_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}.md"
with md_path.open("w", encoding="utf-8") as f:
    f.write(f"# WorldSpec 生成稳定率报告\n\n")
    f.write(f"**生成时间**: {datetime.now().isoformat()}\n")
    f.write(f"**样本数**: {total}\n")
    f.write(f"**LLM 可用**: {'是' if service.llm_client else '否（全部走 sample_fallback）'}\n\n")

    f.write("## 总体指标\n\n")
    f.write("| 指标 | 数值 | 比率 |\n")
    f.write("|------|------|------|\n")
    f.write(f"| raw_saved | {raw_count}/{total} | {raw_count/total:.1%} |\n")
    f.write(f"| json_parse_success | {json_ok}/{total} | {json_ok/total:.1%} |\n")
    f.write(f"| pydantic_valid | {pydantic_ok}/{total} | {pydantic_ok/total:.1%} |\n")
    f.write(f"| validator_valid | {validator_ok}/{total} | {validator_ok/total:.1%} |\n")
    f.write(f"| fallback_used | {fallback_count}/{total} | {fallback_count/total:.1%} |\n")
    f.write(f"| repair_used | {repair_count}/{total} | {repair_count/total:.1%} |\n")
    f.write(f"| errors | {error_count}/{total} | {error_count/total:.1%} |\n\n")

    f.write("## 逐条明细\n\n")
    f.write("| # | idea | source | raw | parse | pydantic | validator | fallback | actions | tensions | quests | error |\n")
    f.write("|---|------|--------|-----|-------|----------|-----------|----------|---------|----------|--------|-------|\n")
    for i, r in enumerate(results):
        f.write(
            f"| {i+1} | {r['idea']} | {r['source']} "
            f"| {'✅' if r['raw_saved'] else '❌'} "
            f"| {'✅' if r['json_parse_success'] else '❌'} "
            f"| {'✅' if r['pydantic_valid'] else '❌'} "
            f"| {'✅' if r['validator_valid'] else '❌'} "
            f"| {'✅' if r['fallback_used'] else '—'} "
            f"| {r['action_template_count']} | {r['tension_count']} | {r['quest_count']} "
            f"| {r['main_error'][:60] if r['main_error'] else '—'} |\n"
        )

    f.write(f"\n## 结论\n\n")
    if service.llm_client is None:
        f.write("当前无 LLM，全部走 `sample_fallback`。本报告验证 pipeline 可运行，稳定率指标需在接入 LLM 后生效。\n")
    elif validator_ok == total:
        f.write("所有样本 validator 通过。\n")
    else:
        f.write(f"{validator_ok}/{total} 样本 validator 通过，{fallback_count} 个走 fallback。\n")

print(f"CSV  → {csv_path}")
print(f"MD   → {md_path}")
print(f"\n总计: {total} | raw: {raw_count} | parse: {json_ok} | pydantic: {pydantic_ok} | validator: {validator_ok} | fallback: {fallback_count} | errors: {error_count}")
