"""
批量 WorldSpec 生成稳定率测试脚本（P1-01）
用于统计 raw_saved_rate / parse_success / pydantic_valid / validator_valid / fallback_rate
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from game_world_kg.service import GameWorldService
from game_world_kg.repository import WorldSpecRepository

# 示例 10 个世界 idea
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
    "江湖客栈门派纷争小世界"
]

OUTPUT_CSV = Path(f"docs/worldspec-generation-stability-report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

# 初始化服务
service = GameWorldService(WorldSpecRepository())

results = []

for idea in WORLD_IDEAS:
    record = {
        'idea': idea,
        'raw_saved': False,
        'json_parse_success': False,
        'pydantic_valid': False,
        'validator_valid': False,
        'repair_used': False,
        'fallback_used': False,
        'action_template_count': 0,
        'tension_count': 0,
        'quest_count': 0,
        'bootstrap_success': False,
        'main_error': ''
    }
    try:
        candidate = service.generate_worldspec(idea)
        record['raw_saved'] = candidate.raw_saved
        record['json_parse_success'] = candidate.json_parse_success
        record['pydantic_valid'] = candidate.pydantic_valid
        record['validator_valid'] = candidate.validator_valid
        record['repair_used'] = candidate.repair_used
        record['fallback_used'] = candidate.fallback_used
        record['action_template_count'] = len(candidate.action_templates)
        record['tension_count'] = len(candidate.initial_tensions)
        record['quest_count'] = len(candidate.initial_quests)
        record['bootstrap_success'] = candidate.bootstrap_success
    except Exception as e:
        record['main_error'] = str(e)
    results.append(record)

# 写入 CSV
with OUTPUT_CSV.open('w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
    writer.writeheader()
    for r in results:
        writer.writerow(r)

print(f"Batch WorldSpec generation report saved to {OUTPUT_CSV}")