# WorldSpec 生成失败分析

> 基于 2026-05-29 批量生成报告 (10 samples, AnthropicClient)

## 1. 总览

| 指标 | 数值 |
|---|---|
| 样本数 | 10 |
| LLM direct parse 成功 | 5 (50%) |
| Fallback 使用 | 5 (50%) |
| Final valid (含 fallback) | 10 (100%) |
| 崩溃 | 0 |

## 2. 失败样本

5 个 fallback 样本（LLM JSON parse 失败→回退 sample）：

| # | idea | source | trace_id |
|---|---|---|---|
| 1 | 青溪镇修仙药铺小世界 | sample_fallback | `trace_worldspec_44149e04ae9e8ade` |
| 2 | 海上漂流木筏小世界 | sample_fallback | `trace_worldspec_2534ad8aa7592636` |
| 4 | 边境驿站谍影小世界 | sample_fallback | `trace_worldspec_17a7a0197928f4df` |
| 5 | 雪山温泉旅馆小世界 | sample_fallback | `trace_worldspec_770a410813a059b0` |
| 10 | 江湖客栈门派纷争小世界 | sample_fallback | `trace_worldspec_6ce1b11a5f10cf8c` |

5 个成功样本输出 `repaired_llm_candidate`，action_template 8-10、tension 3、quest 2-3，结构有效。

## 3. 成功样本

| # | idea | actions | tensions | quests |
|---|---|---|---|---|
| 3 | 地铁末班车求生小世界 | 9 | 3 | 3 |
| 6 | 废土水塔社区小世界 | 8 | 3 | 2 |
| 7 | 魔法学院禁书室小世界 | 8 | 3 | 3 |
| 8 | 山村祭典前夜小世界 | 10 | 3 | 2 |
| 9 | 太空货舱事故小世界 | 10 | 3 | 2 |

## 4. 失败原因推断

已确认 `GAME_WORLD_KG_LLM_MAX_TOKENS=24000`，排除截断。`_loads_json_object()` 已处理 markdown fence strip。失败点在以下两处之一：

### 4.1 `_loads_json_object()` 失败 → LLMError

`llm.py:273` 的 `_loads_json_object()` 从 LLM 返回文本中提取 `{...}` 然后 `json.loads()`。如果 LLM 返回的不是合法 JSON 对象（如纯文本描述、空响应、嵌套错误），抛出 `LLMError`。

### 4.2 `WorldSpec.model_validate()` 失败 → ValidationError

JSON parse 成功但 Pydantic schema 校验失败。例如：缺少必填字段、字段类型错误、`action_templates` 中引用了不存在的 `target_id` 等。

### 4.3 无法区分的原因

`WorldSpecGenerator._generate_with_llm()` (line 542) 用 `except Exception as exc` 统一捕获，只存 `self.last_error`，不区分 `LLMError` 和 `ValidationError`。5 个失败样本的具体错误类型未知。

## 5. 当前容错路径

```
LLM response → json.loads() → Pydantic model_validate → Validator
                    ↓ 失败
              worldspec_generator 捕获 → fallback_reason 记录
                    ↓
              使用 sample_world_spec("village") 作为 adopted_spec
                    ↓
              仍然通过 pydantic + validator (100%)
```

**问题**：LLM parse 失败直接跳到 sample fallback，跳过了 `JsonRepairer` 的 localized repair。

## 6. 修复方案

### 6.1 区分 JSON parse 失败 vs Schema 校验失败（P0）

当前 `_generate_with_llm` 统一 `except Exception`，丢失了失败原因。修改为分别记录：

```python
# worldspec.py _generate_with_llm
try:
    payload = self.llm_client.complete_json(...)
    self.last_candidate_payload = payload
    self.last_json_parse_error = None
    spec = WorldSpec.model_validate(payload)
    self.last_validation_error = None
    return spec
except LLMError as exc:       # JSON parse 失败
    self.last_json_parse_error = str(exc)
    self.last_error = str(exc)
    return None
except ValidationError as exc:  # Schema 校验失败
    self.last_validation_error = str(exc)
    self.last_error = str(exc)
    return None
```

### 6.2 Schema 校验失败时先用 WorldSpecRepairer 修复（P1）

当前 `generate()` → `_generate_with_llm()` 失败 → 直接 `sample_fallback`。应插入 repair 步骤：

```
LLM JSON parse 成功 → model_validate 失败 → WorldSpecRepairer.repair() → model_validate 重试
                                                    ↓ 仍失败
                                              sample fallback
```

`WorldSpecRepairer.repair()` 已能修复 disconnected locations、missing goals、dangling refs 等常见问题，但 `WorldSpecGenerator` 未在 parse 成功后调用它。

### 6.3 持久化 raw response 用于离线分析（P2）

`eval_worldspec_generation.py` 使用 `:memory:` 导致 raw response 丢失。改为文件 DB：

```python
conn = connect("eval_worldspec.db")
```

并在报告中输出 `last_error` 字段，区分 parse 和 schema 错误。

## 7. 优先级建议

| 优先级 | 方案 | 预期效果 |
|---|---|---|
| P0 | 6.1 区分 parse vs schema 错误 | 知道 50% 失败的真正原因 |
| P1 | 6.2 schema 失败先 repair | 减少 fallback，parse 率 50%→70%+ |
| P2 | 6.3 持久化 raw response | 事后精确分析 |
