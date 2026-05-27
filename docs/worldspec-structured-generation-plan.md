# WorldSpec 结构化生成提示词与编译管线方案

## 1. 背景与定位

当前项目已经明确了 **WorldSpec 应该生成什么**：

```text
WorldSpec 只是候选，不是真值；
EventLog 是 source of truth；
LLM 不能直接改 canonical；
ActionTemplate 必须能编译到 Predicate + Effect；
Quest 必须来自 Tension；
NPC memory 必须区分 canonical / npc / faction / rumor / player；
小世界要小而密、可运行、可回放、可解释。
```

但当前生成链路还没有稳定解决：

```text
怎么让 LLM 稳定生成可执行 WorldSpec DSL。
```

实际问题表现为：

```text
LLM 能理解题材，也能输出合法 JSON，
但经常生成“游戏设定 JSON”，不是“可执行 WorldSpec DSL”。
```

典型错误：

```text
action_templates 使用 id/title/description/effects 字符串；
effects 是自然语言或字符串，不是结构化 effect object；
quest objectives 是自然语言字符串；
rules 是自然语言规则；
memory / faction / resource / initial_state 字段和本地 schema 不一致；
一次性生成完整 WorldSpec 时容易字段漂移、引用悬空、数量不达标。
```

本方案解决的是：

> 研究报告解决“生成什么”，本方案解决“怎么稳定生成出来”。

---

## 2. 核心判断

### 2.1 问题不是单纯模型能力问题

当前问题由四部分叠加造成：

```text
1. Prompt 问题：没有把 WorldSpec 明确描述为可执行 DSL。
2. Schema 问题：字段多、嵌套深、引用多，模型容易漂移。
3. 流程问题：一次性生成完整 WorldSpec，错误难定位、难修复。
4. Validator 问题：部分错误表现为 KeyError / AttributeError，而不是结构化 validation issue。
```

因此不能靠继续补几个 alias 彻底解决。

### 2.2 合法 JSON 不等于可执行 WorldSpec

LLM 输出合法 JSON 只能说明语法正确，不能说明：

```text
ActionTemplate 能被 RuleEngine 执行；
Effect 类型受支持；
Quest objective 可验证；
Memory scope 不污染 canonical；
引用实体真实存在；
世界可 bootstrap / replay / play。
```

所以生成链路必须是：

```text
LLM candidate
→ parse
→ normalize safe aliases
→ validate
→ repair if possible
→ validate again
→ adopt or fallback
```

---

## 3. 第一阶段目标

第一阶段不做完整分块生成系统，只做 **结构化生成最小闭环**。

目标：

```text
让当前一次性 WorldSpec 生成变得可约束、可追踪、可拒绝、可 fallback。
```

第一阶段做：

```text
1. 把 prompt 模板模块化。
2. 强化 ActionTemplate / Effect / Quest / Memory 的正反例。
3. Normalizer 只修安全 alias。
4. Validator 明确拒绝不可执行结构。
5. 保存完整 Generation Trace。
6. 增加 debug/latest 调试入口。
```

第一阶段暂不做：

```text
1. 完整多阶段分块生成。
2. 复杂 LLM repair loop。
3. json_schema / grammar constrained decoding 强依赖。
4. 让 Repairer 猜测自然语言 effect 的语义。
```

---

## 4. 第一阶段生成链路

```text
User World Idea
→ WorldIntentExtractor
→ WorldSpecPromptTemplates.build_full_worldspec_prompt()
→ LLM raw response
→ JSON parse
→ WorldSpecNormalizer.normalize_safe_aliases()
→ WorldSpecValidator.validate()
→ WorldSpecRepairer.repair_format_only() 可选
→ WorldSpecValidator.validate()
→ adopted spec or sample fallback
→ GenerationTrace 保存
```

严格约束：

```text
LLM raw response 永远只是 candidate；
invalid candidate 不得写 canonical；
fallback sample 必须按 requested_genre 选择，不能题材污染；
所有错误都必须进入 validation_report 或 generation_error。
```

---

## 5. Prompt 模板设计

新增模块：

```text
src/game_world_kg/worldspec_prompt_templates.py
```

第一阶段先提供一个主模板：

```text
build_full_worldspec_prompt(intent, schema_notes, examples) -> list[dict]
```

后续第二阶段再拆成 block prompt。

### 5.1 System Prompt 原则

System prompt 必须强调：

```text
You are compiling an executable WorldSpec DSL, not writing game setting prose.
Output one strictly valid JSON object only.
Every action must be executable by RuleEngine.
All effects must be structured objects.
Do not output natural-language rules as executable rules.
Do not output string effects.
Do not output string quest objectives.
NPC beliefs must not use canonical memory scope.
If a mechanic cannot be expressed with supported predicates/effects, omit it.
```

### 5.2 必须给模型的核心正例

#### 正确 ActionTemplate

```json
{
  "action_id": "ask_about_topic",
  "label_template": "向{target}询问{topic}",
  "target_selector": {
    "entity_type": "Character",
    "same_location": true
  },
  "arg_schema": {
    "topic": "string"
  },
  "preconditions": [
    {
      "type": "same_location",
      "a": "player",
      "b": "$target"
    }
  ],
  "effects": [
    {
      "type": "add_conversation_event",
      "actor": "player",
      "target": "$target",
      "topic": "$topic"
    }
  ],
  "risk": "low"
}
```

#### 正确 Effect Object

```json
{
  "type": "set_state",
  "entity": "player",
  "attr": "ready",
  "value": true
}
```

#### 正确 Quest Objective

```json
{
  "type": "collect_evidence",
  "target": "ledger_clue"
}
```

#### 正确 Memory Scope

```json
{
  "owner_id": "npc_mara",
  "memory_text": "玩家曾帮我修补过木筏。",
  "truth_scope": "npc",
  "scope_key": "npc_mara",
  "salience": 0.7,
  "confidence": 0.8
}
```

### 5.3 必须给模型的反例

#### 错误 ActionTemplate

```json
{
  "id": "serve_guest",
  "title": "接待客人",
  "description": "完成一次服务。",
  "effects": ["delta_resource: gold,+10"]
}
```

拒绝原因：

```text
missing action_id；
missing label_template；
effects 是字符串；
无法被 RuleEngine 执行。
```

#### 错误 string effect

```json
"set_state: player, state=ready"
```

拒绝原因：

```text
Effect 必须是 object，且 type 必须来自 supported effects。
```

#### 错误 natural-language objective

```json
"完成一次接待并获得声望"
```

拒绝原因：

```text
Quest objective 必须是结构化 object，不能是自然语言字符串。
```

#### 错误 canonical contamination

```json
{
  "owner_id": "npc_mara",
  "memory_text": "玩家一定偷了钥匙。",
  "truth_scope": "canonical",
  "scope_key": "world"
}
```

拒绝原因：

```text
NPC belief 不能写入 canonical。主观判断必须使用 npc 或 rumor scope。
```

---

## 6. Normalizer 边界

Normalizer 只允许修 **安全 alias**。

### 6.1 可以自动修

```text
scale: small -> small_dense
player_start.location -> player_start.location_id
location -> location_id
start_location_id -> start_location
stable_key 缺失时 stable_key = id
locations[].type -> locations[].location_type
characters[].location -> characters[].start_location
items[].owner -> items[].owner_id
items[].location -> items[].location_id
tensions[].type -> tensions[].tension_type
tensions[].targets -> tensions[].affected_entities
quests[].issuer -> quests[].issuer_id
quests[].tension -> quests[].tension_id
action_templates[].id -> action_templates[].action_id
action_templates[].title -> action_templates[].label_template
缺 target_selector -> {}
缺 arg_schema -> {}
缺 preconditions -> []
缺 risk -> "low"
```

### 6.2 不能自动修

```text
string effect -> effect object
自然语言 rule -> executable rule
自然语言 objective -> structured objective
unsupported effect -> add_memory
未知 action 语义 -> 任意可执行 action
引用不存在实体 -> 自动新建实体
```

原则：

> Normalizer 只能修字段名和无语义歧义的默认值，不能猜测游戏逻辑。

---

## 7. Validator 强化方向

Validator 必须把常见失败变成结构化 issue，而不是抛 KeyError / AttributeError。

新增或明确错误码：

```text
action_template_missing_action_id
action_effect_must_be_object
action_precondition_must_be_object
unsupported_effect_type
unsupported_predicate_type
quest_objective_must_be_object
rule_must_not_be_free_text
memory_scope_canonical_contamination
faction_missing_faction_type
resource_shape_invalid
initial_state_shape_invalid
reference_not_found
scale_constraint_failed
```

示例：

```json
{
  "code": "action_effect_must_be_object",
  "path": "action_templates[0].effects[0]",
  "message": "Action effect must be a structured object, not a string."
}
```

---

## 8. Repairer 边界

第一阶段 Repairer 只做格式层修复。

允许：

```text
补 stable_key；
补 target_selector / arg_schema / preconditions / risk；
按 genre 补缺失规模；
修 player_start.location_id；
修明显 alias。
```

不允许：

```text
把自然语言 effect 猜成结构化 effect；
把自然语言 rule 编译成 rule；
把自然语言 objective 编译成 objective；
把 unknown effect 替换成 add_memory；
让 invalid candidate 通过校验只为了减少 fallback。
```

如果结构语义不明确：

```text
reject candidate
→ fallback sample
→ trace 中记录 validation_report
```

---

## 9. Generation Trace 设计

新增或完善生成追踪结构。

每次生成保存：

```json
{
  "trace_id": "...",
  "created_at": "...",
  "requested_idea": "...",
  "requested_genre": "ocean",
  "source": "llm_candidate | repaired_llm_candidate | sample_fallback",
  "raw_llm_response": "...",
  "parsed_candidate": {},
  "normalized_candidate": {},
  "validation_report": {},
  "repair_attempts": [],
  "adopted_spec": {},
  "adopted_spec_genre": "ocean",
  "fallback_reason": "...",
  "warnings": []
}
```

保存位置：

```text
source_texts.source_type = worldspec_generation_trace
```

同时保留现有：

```text
source_texts.source_type = worldspec_candidate
```

但新 trace 是调试主入口。

---

## 10. Debug 接口

新增：

```text
GET /v1/worldspec/debug/latest
GET /v1/worldspec/debug/{trace_id}
```

返回最近一次生成 trace。

用途：

```text
查看原始模型输出；
查看 parsed candidate；
查看 normalizer 改了什么；
查看 validator 为什么拒绝；
查看最终 adopted spec；
查看 fallback 是否题材污染。
```

---

## 11. 第二阶段：分块生成

第一阶段稳定后，再做分块生成。

目标链路：

```text
WorldIntent
→ WorldSkeleton
→ EntityBlocks
→ ActionTemplateBlocks
→ TensionQuestMemoryBlocks
→ Merge
→ Validate
→ Repair
→ Adopt
```

建议新增模块：

```text
worldspec_blocks.py
worldspec_block_generator.py
worldspec_block_validators.py
worldspec_repair_prompts.py
```

每个 block 使用独立 prompt、独立 schema、独立 validation report。

优先拆最容易失败的块：

```text
ActionTemplateBlock
TensionQuestBlock
MemoryBlock
```

---

## 12. JSON Schema / Constrained Decoding 建议

如果本地 OpenAI-compatible 服务支持：

```text
response_format=json_schema
grammar constrained decoding
```

建议使用，但不要第一阶段强依赖。

使用顺序：

```text
1. ActionTemplateBlockSchema
2. QuestBlockSchema
3. MemoryBlockSchema
4. EntityBlockSchema
5. WorldSkeletonSchema
```

不建议第一阶段直接对完整 WorldSpec 使用大 schema，因为：

```text
schema 太大；
错误难定位；
模型容易在引用一致性上失败；
即使结构合法，也不能保证地图连通、entity id 存在、quest 来自 tension。
```

即使用 constrained decoding，Validator 仍然是最终裁判。

---

## 13. 评估指标

第一阶段新增评估指标：

```text
json_parse_success_rate
schema_valid_rate
normalizer_recovery_rate
fallback_rate
action_template_valid_rate
effect_object_rate
quest_objective_object_rate
memory_scope_valid_rate
reference_integrity_rate
adopted_spec_genre_match_rate
world_bootstrap_success_rate
```

最低验收：

```text
string effects 不得通过；
string objectives 不得通过；
free-text rules 不得作为 executable rule；
invalid candidate 不得 bootstrap；
fallback spec 不得题材污染；
trace 必须保存 raw/parsed/normalized/report/adopted。
```

---

## 14. 第一阶段开发任务

### SG-01 新增本文档

```text
docs/worldspec-structured-generation-plan.md
```

### SG-02 新增 prompt 模板模块

```text
src/game_world_kg/worldspec_prompt_templates.py
```

内容：

```text
build_full_worldspec_prompt()
ACTION_TEMPLATE_VALID_EXAMPLE
ACTION_TEMPLATE_INVALID_EXAMPLE
EFFECT_VALID_EXAMPLE
EFFECT_INVALID_EXAMPLE
QUEST_OBJECTIVE_VALID_EXAMPLE
QUEST_OBJECTIVE_INVALID_EXAMPLE
MEMORY_SCOPE_VALID_EXAMPLE
MEMORY_SCOPE_INVALID_EXAMPLE
```

### SG-03 修改 WorldSpecGenerator

要求：

```text
使用 prompt_templates；
保存 raw_llm_response；
保存 parsed_candidate；
保存 normalized_candidate；
保存 validation_report；
保存 adopted_spec；
source 明确为 llm_candidate / repaired_llm_candidate / sample_fallback。
```

### SG-04 强化 WorldSpecNormalizer

只做安全 alias，不做语义猜测。

重点补：

```text
action_templates[].id -> action_id
action_templates[].title -> label_template
scale small -> small_dense
缺 target_selector / arg_schema / preconditions / risk
```

### SG-05 强化 WorldSpecValidator

必须结构化拒绝：

```text
string effects
string objectives
free-text executable rules
missing action_id
canonical contamination
unsupported predicates/effects
```

### SG-06 增加 Generation Trace

保存到：

```text
source_texts.source_type = worldspec_generation_trace
```

### SG-07 增加 Debug API

```text
GET /v1/worldspec/debug/latest
GET /v1/worldspec/debug/{trace_id}
```

### SG-08 增加测试

必须覆盖：

```text
LLM 返回 id/title/string effects 时：id/title 可 normalize，string effects 必须拒绝；
quest objectives 为字符串时必须拒绝；
rules 为自然语言字符串时必须拒绝；
NPC memory truth_scope=canonical 必须拒绝；
invalid candidate fallback 后 adopted spec genre 与 requested genre 一致；
trace 保存 raw/parsed/normalized/report/adopted；
/worldspec/debug/latest 能返回最近 trace。
```

---

## 15. 与 Beta 3 游戏开发的关系

本阶段是继续推进 Beta 3 游戏开发前的生成稳定性补强。

原因：

```text
Playable Game Layer 依赖稳定 WorldSpec；
如果 WorldSpec 生成的是设定 JSON，后续 UI、任务、NPC 自运行都会建立在不可靠数据上。
```

完成本阶段后，继续推进：

```text
PG-03 Player Progression
PG-04 Quest / Tension Journal
PG-05 Relationship / Faction / Permission Panels
PG-06 Foreground NPC Scheduler
```

---

## 16. 完成定义

第一阶段完成时，必须满足：

```text
1. LLM 生成 action_templates 时，不再因为缺 action_id 变成 KeyError。
2. string effects 会被明确 validation issue 拒绝。
3. string objectives 会被明确 validation issue 拒绝。
4. free-text rules 不会进入 executable rule。
5. invalid candidate 不会 bootstrap。
6. fallback sample 不发生 genre contamination。
7. 每次生成都能通过 debug/latest 查看 raw/parsed/normalized/report/adopted。
8. 当前一次性生成链路仍可用，现有 WorldSpec / Beta 3 测试不破坏。
```

一句话：

> 第一阶段不是让 LLM 一次生成完美世界，而是让 WorldSpec 生成从“不可控 JSON 输出”变成“可诊断、可校验、可拒绝、可 fallback 的 DSL 生成候选”。
