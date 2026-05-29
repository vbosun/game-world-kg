# WorldSpec 生成稳定率报告

**生成时间**: 2026-05-29T14:07:31.747422
**样本数**: 10
**LLM 可用**: 是

## 总体指标

| 指标 | 数值 | 比率 |
|------|------|------|
| raw_saved | 10/10 | 100.0% |
| json_parse_success | 5/10 | 50.0% |
| pydantic_valid | 10/10 | 100.0% |
| validator_valid | 10/10 | 100.0% |
| fallback_used | 5/10 | 50.0% |
| repair_used | 0/10 | 0.0% |
| errors | 0/10 | 0.0% |

## 逐条明细

| # | idea | source | raw | parse | pydantic | validator | fallback | actions | tensions | quests | error |
|---|------|--------|-----|-------|----------|-----------|----------|---------|----------|--------|-------|
| 1 | 青溪镇修仙药铺小世界 | sample_fallback | ✅ | ❌ | ✅ | ✅ | ✅ | 10 | 3 | 2 | — |
| 2 | 海上漂流木筏小世界 | sample_fallback | ✅ | ❌ | ✅ | ✅ | ✅ | 10 | 3 | 2 | — |
| 3 | 地铁末班车求生小世界 | repaired_llm_candidate | ✅ | ✅ | ✅ | ✅ | — | 9 | 3 | 3 | — |
| 4 | 边境驿站谍影小世界 | sample_fallback | ✅ | ❌ | ✅ | ✅ | ✅ | 10 | 3 | 2 | — |
| 5 | 雪山温泉旅馆小世界 | sample_fallback | ✅ | ❌ | ✅ | ✅ | ✅ | 10 | 3 | 2 | — |
| 6 | 废土水塔社区小世界 | repaired_llm_candidate | ✅ | ✅ | ✅ | ✅ | — | 8 | 3 | 2 | — |
| 7 | 魔法学院禁书室小世界 | repaired_llm_candidate | ✅ | ✅ | ✅ | ✅ | — | 8 | 3 | 3 | — |
| 8 | 山村祭典前夜小世界 | repaired_llm_candidate | ✅ | ✅ | ✅ | ✅ | — | 10 | 3 | 2 | — |
| 9 | 太空货舱事故小世界 | repaired_llm_candidate | ✅ | ✅ | ✅ | ✅ | — | 10 | 3 | 2 | — |
| 10 | 江湖客栈门派纷争小世界 | sample_fallback | ✅ | ❌ | ✅ | ✅ | ✅ | 10 | 3 | 2 | — |

## 结论

所有样本 validator 通过。
