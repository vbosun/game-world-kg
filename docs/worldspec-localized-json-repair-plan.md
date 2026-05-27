# WorldSpec 局部 JSON 修复开发方案

## 1. 背景

当前 WorldSpec 生成链路已经能让模型输出较完整的世界候选，但仍会出现 JSON 语法级错误，例如：

```text
缺逗号；
尾逗号；
markdown ```json 包裹；
JSON 前后混入说明文字；
对象/数组括号轻微不平衡；
字符串转义错误。
```

这些问题和 WorldSpec schema 校验问题不同：

```text
JSONDecodeError：原始文本不是合法 JSON，无法进入 normalizer / validator。
ValidationError：JSON 已合法，但不符合 WorldSpec schema / DSL 约束。
```

本方案只解决第一类：

> 原始 LLM 输出内容基本完整，但 JSON 语法局部损坏。

---

## 2. 核心原则

### 2.1 不把完整 WorldSpec 交给修复模型

完整 WorldSpec 太长，小模型容易：

```text
修一处，改坏别处；
偷偷删字段；
重写内容；
把 JSON syntax repair 和 WorldSpec schema repair 混在一起；
输出再次超长或格式坏。
```

因此只允许：

```text
定位 JSONDecodeError 附近的局部片段；
把局部片段交给本地小模型；
让它只修这段 JSON 语法；
替换回全文；
重新整体 json.loads。
```

### 2.2 修复模型只修 JSON 语法，不修 WorldSpec 语义

允许修：

```text
少逗号；
尾逗号；
markdown fences；
JSON 前后说明文字；
注释；
单双引号轻微错误；
字符串未转义引号；
括号/中括号轻微不平衡。
```

不允许修：

```text
补 action_id；
把 string effect 转成 effect object；
把自然语言 rule 编译成 rule；
把自然语言 objective 编译成 objective；
补 tension.description；
补 character.goals.goal_id；
修复引用不存在；
补地点/NPC数量；
改变题材或世界内容。
```

这些属于：

```text
WorldSpecNormalizer / WorldSpecValidator / WorldSpecRepairer
```

而不是 JSON repair。

---

## 3. 目标链路

新增 localized JSON repair 后，WorldSpec 生成链路变为：

```text
WorldSpec prompt
→ main LLM raw response
→ extract_json_candidate(raw)
→ cheap_sanitize_json_text(text)
→ json.loads(text)
   → 成功：进入 WorldSpecNormalizer / Validator
   → 失败 JSONDecodeError：进入 localized JSON repair loop
→ LocalizedJsonRepairer 截取错误窗口
→ 本地小模型只修局部 fragment
→ 替换回全文
→ 重新整体 json.loads
→ 成功：进入 WorldSpecNormalizer / Validator
→ 仍失败：sample fallback，并保存 trace
```

重要边界：

```text
只有 JSONDecodeError 触发 localized JSON repair；
WorldSpec ValidationError 不触发 JSON repair。
```

---

## 4. 配置设计

新增配置类：

```python
@dataclass(frozen=True)
class JsonRepairConfig:
    enabled: bool
    mode: str
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    temperature: float
    max_tokens: int
    max_attempts: int
    window_lines: int
```

建议环境变量：

```env
WORLDGEN_JSON_REPAIR_ENABLED=true
WORLDGEN_JSON_REPAIR_MODE=localized
WORLDGEN_JSON_REPAIR_PROVIDER=openai_compatible
WORLDGEN_JSON_REPAIR_BASE_URL=http://127.0.0.1:8000/v1
WORLDGEN_JSON_REPAIR_API_KEY=EMPTY
WORLDGEN_JSON_REPAIR_MODEL=qwen2.5-coder-7b-instruct
WORLDGEN_JSON_REPAIR_TIMEOUT_SECONDS=20
WORLDGEN_JSON_REPAIR_TEMPERATURE=0
WORLDGEN_JSON_REPAIR_MAX_TOKENS=4096
WORLDGEN_JSON_REPAIR_MAX_ATTEMPTS=2
WORLDGEN_JSON_REPAIR_WINDOW_LINES=8
```

默认建议：

```text
enabled = false
mode = localized
temperature = 0
max_attempts = 2
window_lines = 8
```

不建议默认开启，避免影响已有测试和生成链路。

---

## 5. 模型建议

JSON 局部修复不需要大模型，优先使用 coder / instruct 小模型。

推荐：

```text
Qwen2.5-Coder-7B-Instruct Q4_K_M / Q5_K_M
Qwen2.5-Coder-3B-Instruct Q5_K_M
Qwen3-8B-Instruct Q4_K_M
Qwen3-4B-Instruct Q5_K_M
```

不建议使用：

```text
VL 模型；
abliterated 模型；
高温 creative 模型。
```

---

## 6. 新增模块

新增文件：

```text
src/game_world_kg/json_repair.py
```

### 6.1 数据结构

```python
@dataclass
class JsonRepairAttempt:
    attempt: int
    error: str
    start_line: int
    end_line: int
    fragment_before: str
    fragment_after: str | None
    changed: bool
    success_after_replace: bool | None
    repair_error: str | None = None


@dataclass
class JsonRepairResult:
    success: bool
    parsed_json: dict[str, Any] | None
    repaired_text: str | None
    error: str | None
    attempts: list[JsonRepairAttempt]
    json_repair_used: bool
    json_repair_mode: str
```

### 6.2 函数

```python
def extract_json_candidate(raw_text: str) -> str:
    """Extract the likely JSON object from raw LLM text.

    Steps:
    - strip whitespace
    - remove markdown fences if the whole output is fenced
    - find first '{' and last '}'
    - return substring
    """


def cheap_sanitize_json_text(text: str) -> str:
    """Cheap deterministic cleanup before model repair.

    Allowed:
    - remove ```json fences
    - strip BOM
    - remove trailing prose outside first {...last}
    - optionally remove trailing commas before } or ]
    """


def format_json_error(text: str, exc: json.JSONDecodeError) -> str:
    """Return line/column/char and short context."""


def extract_error_window(text: str, lineno: int, before: int, after: int) -> tuple[int, int, str]:
    """Return 0-based start line, exclusive end line, and fragment."""


def replace_error_window(text: str, start: int, end: int, repaired_fragment: str) -> str:
    """Replace line window with repaired fragment."""
```

### 6.3 类

```python
class LocalizedJsonRepairer:
    def __init__(self, client: LLMClient, config: JsonRepairConfig) -> None:
        ...

    def parse_or_repair(self, raw_text: str) -> JsonRepairResult:
        ...

    def repair_fragment(self, fragment: str, error: str, start_line: int, end_line: int) -> str:
        ...
```

---

## 7. 循环设计

需要循环，但必须受限。

推荐：

```text
WORLDGEN_JSON_REPAIR_MAX_ATTEMPTS=2
```

循环逻辑：

```python
text = extract_json_candidate(raw_text)
text = cheap_sanitize_json_text(text)
attempts = []

for attempt_index in range(max_attempts + 1):
    try:
        parsed = json.loads(text)
        return success(parsed, text, attempts)
    except json.JSONDecodeError as exc:
        if attempt_index >= max_attempts:
            return failed(format_json_error(text, exc), attempts)

        start, end, fragment = extract_error_window(
            text,
            lineno=exc.lineno,
            before=config.window_lines,
            after=config.window_lines,
        )

        repaired_fragment = repair_fragment(
            fragment=fragment,
            error=format_json_error(text, exc),
            start_line=start + 1,
            end_line=end,
        )

        new_text = replace_error_window(text, start, end, repaired_fragment)
        changed = new_text != text

        attempts.append(...)

        if not changed:
            return failed("repair produced no change", attempts)

        text = new_text
```

退出条件：

```text
1. json.loads 成功；
2. 达到 max_attempts；
3. repair model 返回空；
4. repaired fragment 替换后全文无变化；
5. repair model 报错或超时。
```

每轮必须：

```text
修复局部 fragment；
替换回完整 JSON；
重新对完整 JSON json.loads；
如果仍失败，再根据新的 JSONDecodeError 定位新的局部。
```

不能只对局部 fragment 做 json.loads，因为 fragment 本身可能不是完整 JSON。

---

## 8. 修复 Prompt

Localized repair system prompt：

```text
You are a local JSON syntax patcher.

You will receive a small broken JSON fragment from a larger JSON object.

Task:
Fix only this fragment so it becomes valid JSON when inserted back into the original document.

Rules:
- Preserve all keys, values, ids, names, Chinese text, and ordering.
- Do not add new world content.
- Do not remove fields.
- Do not rewrite schema.
- Do not fix WorldSpec validation.
- Do not add missing required fields.
- Do not convert string effects into objects.
- Do not convert natural-language objectives into objects.
- Only fix JSON syntax: missing commas, trailing commas, unescaped quotes, broken braces/brackets, markdown fences, or comments.
- Return only the repaired fragment.
- No markdown.
- No explanation.
```

User payload：

```json
{
  "json_error": "Expecting ',' delimiter at line 135 column 8",
  "fragment_start_line": 127,
  "fragment_end_line": 143,
  "fragment": "..."
}
```

---

## 9. 接入点

第一阶段只接入 WorldSpec 生成链路，不改所有 `complete_json()`。

修改：

```text
src/game_world_kg/worldspec_safe.py
```

当前逻辑大概率是：

```python
payload = self.llm_client.complete_json(messages, temperature=0.2)
```

改为：

```python
raw_text = self.llm_client.complete_text(messages, temperature=0.2, timeout_seconds=...)
result = json_parser_or_repairer.parse_or_repair(raw_text)

self.last_raw_response = raw_text
self.last_json_parse_error = result.error
self.last_json_repair_used = result.json_repair_used
self.last_json_repair_mode = result.json_repair_mode
self.last_json_repair_attempts = [attempt.as_dict() for attempt in result.attempts]
self.last_json_repaired_response = result.repaired_text if result.json_repair_used else None

if not result.success:
    self.last_error = "JSONDecodeError: " + (result.error or "unknown JSON parse error")
    return None

payload = result.parsed_json
```

然后继续：

```text
WorldSpecNormalizer
→ WorldSpecValidator
→ WorldSpecRepairer if needed
→ WorldSpecValidator
→ WorldSpec.model_validate
```

注意：

```text
ValidationError 不进入 JSON repair。
```

---

## 10. Repair Client 创建

不要复用主模型配置。

新增 builder：

```python
def build_json_repair_client_from_env() -> LLMClient | None:
    config = JsonRepairConfig.from_env()
    if not config.enabled:
        return None
    return OpenAICompatibleClient(config.to_llm_config())
```

如果需要兼容 Anthropic 协议，也可支持：

```text
WORLDGEN_JSON_REPAIR_PROVIDER=anthropic
```

但第一版推荐只支持 openai_compatible，因为本地小模型一般走 OpenAI-compatible server。

---

## 11. Generation Trace 扩展

在 `worldspec_generation_trace` 中新增字段：

```json
{
  "json_parse_error": "Expecting ',' delimiter at line 135 column 8",
  "json_repair_enabled": true,
  "json_repair_mode": "localized",
  "json_repair_used": true,
  "json_repair_model": "qwen2.5-coder-7b-instruct",
  "json_repaired_response": "... full repaired candidate text ...",
  "json_repair_attempts": [
    {
      "attempt": 1,
      "error": "Expecting ',' delimiter at line 135 column 8",
      "start_line": 127,
      "end_line": 143,
      "fragment_before": "...",
      "fragment_after": "...",
      "changed": true,
      "success_after_replace": false,
      "repair_error": null
    },
    {
      "attempt": 2,
      "error": "Expecting property name enclosed in double quotes at line 221 column 5",
      "start_line": 213,
      "end_line": 229,
      "fragment_before": "...",
      "fragment_after": "...",
      "changed": true,
      "success_after_replace": true,
      "repair_error": null
    }
  ]
}
```

如果没有启用 repair：

```json
{
  "json_repair_enabled": false,
  "json_repair_used": false,
  "json_repair_attempts": []
}
```

---

## 12. Debug API 展示

现有：

```text
GET /v1/worldspec/debug/latest
GET /v1/worldspec/debug/{trace_id}
```

无需新增 API，但返回 payload 应包含 JSON repair 字段。

前端或调试页面可显示：

```text
Raw LLM Response
JSON Parse Error
Repair Mode
Repair Attempts
Fragment Before / After
Repaired Full Text
Parsed Candidate
Validation Report
Adopted Spec
```

---

## 13. 测试计划

新增测试文件建议：

```text
tests/test_json_repair.py
```

### 13.1 基础工具测试

```text
test_extract_json_candidate_removes_markdown_fence
test_extract_json_candidate_strips_prose_before_after_json
test_extract_error_window_returns_expected_lines
test_replace_error_window_replaces_only_window
```

### 13.2 局部修复循环测试

使用 fake repair client。

```text
test_localized_repair_sends_only_fragment_not_full_json
```

断言：

```text
fake client 收到的 fragment 只包含错误窗口；
不包含完整 WorldSpec 全文；
```

```text
test_localized_repair_success_after_one_attempt
```

断言：

```text
少逗号文本第一次 json.loads 失败；
repair client 返回修复 fragment；
替换后整体 json.loads 成功。
```

```text
test_localized_repair_loops_to_second_error
```

断言：

```text
第一处修完后暴露第二处错误；
第二轮继续截取新的错误窗口；
最后成功；
attempts 长度为 2。
```

```text
test_localized_repair_stops_after_max_attempts
```

断言：

```text
超过 max_attempts 后失败；
不无限循环。
```

```text
test_localized_repair_stops_when_no_change
```

断言：

```text
修复模型返回原 fragment；
系统停止并返回失败。
```

### 13.3 边界测试

```text
test_json_repair_does_not_handle_validation_error
```

断言：

```text
JSON 合法但 string effect / missing action_id；
不调用 JsonRepairer；
进入 Validator。
```

```text
test_json_repair_prompt_forbids_schema_repair
```

断言 prompt 包含：

```text
Do not fix WorldSpec validation.
Do not add missing required fields.
Do not convert string effects into objects.
```

### 13.4 Trace 测试

```text
test_worldspec_generation_trace_records_json_repair_attempts
```

断言：

```text
trace 包含 json_parse_error / json_repair_used / json_repair_attempts；
fragment_before / fragment_after 存在；
```

---

## 14. Codex 开发任务

```text
JR-01 新增 JsonRepairConfig 与环境变量解析。
JR-02 新增 src/game_world_kg/json_repair.py，实现 extract / sanitize / error window / replace / LocalizedJsonRepairer。
JR-03 新增 JSON repair prompt，明确只修局部语法，不修 WorldSpec schema。
JR-04 在 worldspec_safe.WorldSpecGenerator 中接入 parse_or_repair，不再直接 complete_json。
JR-05 仅在 JSONDecodeError 时触发 localized repair；ValidationError 不触发。
JR-06 扩展 Generation Trace，记录 json_parse_error / json_repair_used / json_repair_attempts / json_repaired_response。
JR-07 增加 tests/test_json_repair.py，覆盖局部修复、循环、停止条件和 trace。
JR-08 更新 docs/worldspec-structured-generation-plan.md 或 README，说明 JSON repair 与 WorldSpec repair 分层。
```

---

## 15. 验收标准

完成后必须满足：

```text
1. 主模型输出少逗号时，系统能定位错误局部并调用修复模型。
2. 修复模型只收到局部 fragment，不收到完整 WorldSpec raw response。
3. 修复后必须替换回全文并整体 json.loads。
4. 支持最多 N 次循环修复，默认 N=2。
5. 达到 max_attempts 后 fallback，不无限循环。
6. repair 返回无变化时停止。
7. JSON 合法但 WorldSpec schema 错误时，不调用 JSON repair。
8. string effects 不会被 JSON repair 改成 object。
9. trace 能看到每轮 fragment_before / fragment_after。
10. invalid candidate 不会 bootstrap。
```

---

## 16. 与研究报告的一致性

本方案不改变核心研究路线：

```text
LLM 只生成 candidate；
EventLog 是真值源；
WorldSpec 必须经过 Validator；
ActionTemplate 必须可执行；
NPC memory / rumor / canonical 必须隔离；
invalid candidate 不得 bootstrap。
```

JSON repair 是更底层的语法修复层：

```text
LocalizedJsonRepairer：只修 raw text 的 JSON 语法；
WorldSpecNormalizer：只修安全 alias；
WorldSpecValidator：裁判 schema / 引用 / DSL；
WorldSpecRepairer：有限格式修复；
BootstrapCompiler：只有 valid spec 才能写 EventLog。
```

一句话：

> 本地小模型 JSON 修复层只负责把“坏 JSON 文本”修成“可解析 JSON 对象”，不负责让 WorldSpec 变正确，更不负责写入世界真值。
