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

由于此次跑批使用 `:memory:` 数据库，raw LLM 响应在进程结束后丢失，以下基于常见 LLM JSON 生成模式推断：

### 4.1 最可能原因：JSON 截断

`WorldSpecGenerator` 调用 LLM 时 `max_tokens` 默认为 4096。一个完整 WorldSpec JSON 约 3000-8000 tokens。`max_tokens` 不够时 JSON 末尾被截断，缺少闭合 `}`，`json.loads()` 抛出 `JSONDecodeError`。

**证据**：5 个 fallback 样本的 idea 都偏向复杂题材（修仙、谍影、门派纷争），可能需要更长的 JSON 输出。

### 4.2 次要可能原因

| 原因 | 可能性 | 说明 |
|---|---|---|
| LLM 输出前后包裹 markdown 代码块 | 中 | ` ```json ... ``` ` 包裹，`json.loads()` 前未 strip |
| 中文标点混入 JSON key/value | 低 | 中文引号 `""` 被 LLM 用在 JSON 值中 |
| 尾随逗号 | 低 | LLM 常在数组/对象末尾多加逗号 |
| Schema 漂移 | 中 | LLM 返回的结构与 `WorldSpec` Pydantic model 字段不匹配 |

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

### 6.1 增加 max_tokens（低风险，立即生效）

```python
# config.py 或 env
GAME_WORLD_KG_LLM_MAX_TOKENS=8192  # 从 4096 提升
```

### 6.2 LLM 返回后先 strip markdown 包裹（低风险）

在 `WorldSpecGenerator._generate_with_llm()` 中，`json.loads()` 之前增加：

```python
def _strip_markdown_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    return text
```

### 6.3 parse 失败时先尝试 localized repair，再 fallback（中风险）

当前流程是 `LLM parse 失败 → sample fallback`。应改为：

```
LLM parse 失败 → localized JSON repair (truncation fix, markdown strip, trailing comma) → parse
                    ↓ 仍失败
              sample fallback
```

`JsonRepairer` 已有 `_repair_truncated_json()` 和 `_repair_markdown_fence()`，但 `WorldSpecGenerator` 未在 parse 失败时调用。

### 6.4 保留 raw response 用于离线分析（低风险）

当前 `:memory:` 数据库使 raw response 丢失。建议在 `eval_worldspec_generation.py` 中使用文件 DB：

```python
conn = connect("eval_worldspec.db")  # 持久化，便于事后分析
```

## 7. 优先级建议

| 优先级 | 方案 | 预期效果 |
|---|---|---|
| P0 | 6.1 增加 max_tokens | 减少截断，parse 率 50%→70%+ |
| P0 | 6.2 strip markdown fence | 消除代码块包裹失败 |
| P1 | 6.3 parse 失败先 repair | 减少 fallback，parse 率→80%+ |
| P2 | 6.4 持久化 raw response | 支持后续精确分析 |
