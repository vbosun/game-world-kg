# LLM 提示词审查与修复建议

## 1. 审查结论

当前项目中的 LLM prompt 整体方向是正确的：

```text
LLM 只生成 candidate / narration / dialogue；
EventLog 是 source of truth；
RuleEngine 是合法性裁判；
ActionTemplate 必须可执行；
NPC memory / rumor / canonical 必须隔离。
```

但当前 prompt 仍存在几个问题：

```text
1. WorldSpec prompt 只重点强化了 ActionTemplate / Effect / Quest Objective / Memory Scope，尚未覆盖完整 WorldSpec 字段契约。
2. ActionParser 仍有 legacy action id 体系残留。
3. Narrator prompt 可进一步加强“只描述 EventLog / rule_result 已发生事实”。
4. MemoryAwareDialogue prompt 可进一步加强 rumor / confidence 的表达边界。
5. LLMExtractor 仍基于固定 ALLOWED_ACTION_IDS，后续需要升级为动态 WorldSpec ActionTemplate / Affordance 抽取。
```

本修复建议不改变研究报告原则，不让 LLM 写 canonical，不让 prompt 绕过 Validator / RuleEngine / EventLog。

---

## 2. WorldSpec Prompt 修复建议

### 2.1 当前状态

当前 `worldspec_prompt_templates.py` 已经正确强调：

```text
You are compiling an executable WorldSpec DSL, not writing game setting prose.
Do not output string effects.
Do not output string quest objectives.
NPC beliefs must not use canonical memory scope.
```

并且已经加入了：

```text
ActionTemplate 正反例；
Effect 正反例；
Quest Objective 正反例；
Memory Scope 正反例。
```

这说明提示词方向正确。

### 2.2 当前缺口

结合最新模型输出错误：

```text
scale: Input should be 'small_dense'
characters.0.goals.0.goal_id: Field required
characters.0.goals.0.priority: Field required
initial_tensions.0.description: Field required
background_lore: Input should be a valid list
```

可以判断 WorldSpec prompt 的字段契约还不完整。

当前 schema notes 只告诉模型：

```text
character 需要 goals；
tension 需要 id / tension_type / affected_entities / evidence。
```

但没有告诉模型：

```text
scale 必须精确为 small_dense；
character.goals 每一项必须包含 goal_id / priority；
tension 必须包含 description；
background_lore 必须是 list[str]；
faction / resource / initial_state 的对象结构。
```

### 2.3 必须补充的字段契约

修改 `src/game_world_kg/worldspec_prompt_templates.py`，在 `_default_schema_notes()` 或 prompt user content 中补充：

```text
scale must be exactly "small_dense".
background_lore must be list[str], not a single string.

character.goals item must be object with:
- goal_id
- priority
- desired_state
- risk_tolerance

tension must be object with:
- id
- tension_type
- description
- affected_entities
- evidence
- suggested_actions
- priority

faction must be object with:
- id
- stable_key
- name
- faction_type
- goals
- relations

resource must be object with:
- entity
- attr
- value

initial_state must be object with:
- entity
- attr
- value
```

### 2.4 新增正例

新增以下常量：

```python
CHARACTER_GOAL_VALID_EXAMPLE = {
    "goal_id": "gain_freedom",
    "priority": 0.9,
    "desired_state": None,
    "risk_tolerance": 0.4,
}

TENSION_VALID_EXAMPLE = {
    "id": "debt_control",
    "tension_type": "resource_pressure",
    "description": "玩家受到债务和看管限制，必须寻找脱身机会。",
    "affected_entities": ["player", "house_manager", "ledger"],
    "evidence": [
        {"type": "state", "entity": "player", "attr": "debt_status", "value": "bound"}
    ],
    "suggested_actions": ["ask_about_topic", "inspect_object"],
    "priority": 0.8,
}

FACTION_VALID_EXAMPLE = {
    "id": "house_staff",
    "stable_key": "house_staff",
    "name": "馆中管事",
    "faction_type": "organization",
    "goals": ["maintain_control", "protect_income"],
    "relations": [],
}

RESOURCE_VALID_EXAMPLE = {
    "entity": "player",
    "attr": "silver",
    "value": 2,
}

INITIAL_STATE_VALID_EXAMPLE = {
    "entity": "player",
    "attr": "location",
    "value": "start_room",
}

BACKGROUND_LORE_VALID_EXAMPLE = [
    "这座小世界围绕债务、看管、情报和脱身路线展开。",
    "不同势力都在争夺账本、名声和出入许可。",
]
```

### 2.5 新增反例

新增：

```python
SCALE_INVALID_EXAMPLE = {"scale": "small"}
CHARACTER_GOAL_INVALID_EXAMPLE = {"goals": ["逃离这里"]}
TENSION_INVALID_EXAMPLE = {
    "id": "debt_control",
    "tension_type": "resource_pressure",
    "affected_entities": ["player"],
    "evidence": [],
}
BACKGROUND_LORE_INVALID_EXAMPLE = "这是一段单个字符串背景设定。"
FACTION_INVALID_EXAMPLE = {
    "id": "house_staff",
    "name": "馆中管事",
    "members": ["npc_a", "npc_b"],
}
RESOURCE_INVALID_EXAMPLE = "player has 2 silver"
INITIAL_STATE_INVALID_EXAMPLE = "player is in start room"
```

对应拒绝原因：

```text
scale 必须精确为 small_dense；
goals 必须是 object[]，每项包含 goal_id / priority；
tension 必须包含 description；
background_lore 必须是 list[str]；
faction 不能只有 members，必须有 faction_type / goals / relations；
resource / initial_state 必须是结构化 object。
```

### 2.6 Final self-check

在 WorldSpec prompt 中加入：

```text
Before final output, silently verify:
- scale is exactly "small_dense".
- all count constraints are satisfied.
- every character goal has goal_id and priority.
- every tension has description.
- background_lore is an array of strings.
- every faction has faction_type, goals, and relations.
- every resource has entity, attr, value.
- every initial_state has entity, attr, value.
- every action_template has action_id and label_template.
- every precondition and effect is an object.
- no effect is a string.
- no quest objective is a string.
- no executable rule is free text.
- no NPC belief uses canonical scope.
- every referenced id exists.
Only output the final JSON object.
```

---

## 3. Normalizer 修复建议

### 3.1 可安全修复

允许继续自动修：

```text
scale: small -> small_dense
player_start.location -> player_start.location_id
location -> location_id
stable_key 缺失时 stable_key = id
action_templates[].id -> action_id
action_templates[].title -> label_template
缺 target_selector -> {}
缺 arg_schema -> {}
缺 preconditions -> []
缺 risk -> "low"
```

建议新增：

```text
background_lore: string -> [string]
tension.summary -> tension.description
tension.title -> tension.description
```

这些转换没有明显语义猜测，属于字段别名或容器类型修复。

### 3.2 不允许自动修复

继续禁止：

```text
string effect -> effect object
自然语言 rule -> executable rule
自然语言 objective -> structured objective
unsupported effect -> add_memory
未知 action 语义 -> 任意可执行 action
引用不存在实体 -> 自动新建实体
```

原则：

> Normalizer 只能修字段名和无歧义默认值，不能猜游戏逻辑。

---

## 4. Validator 修复建议

当前 Validator 已经加入 preflight 检查：

```text
rule_must_not_be_free_text
action_template_missing_action_id
action_precondition_must_be_object
action_effect_must_be_object
unsupported_effect_type
quest_objective_must_be_object
memory_scope_canonical_contamination
```

建议补充：

```text
scale_must_be_small_dense
character_goal_must_be_object
character_goal_missing_goal_id
character_goal_missing_priority
tension_missing_description
background_lore_must_be_list
faction_missing_faction_type
faction_missing_goals
faction_missing_relations
resource_shape_invalid
initial_state_shape_invalid
initial_memory_shape_invalid
```

注意：这些问题应在 Pydantic 之前 preflight 出来，避免出现不友好的 KeyError / AttributeError / 大段 schema error。

---

## 5. Narrator Prompt 修复建议

当前 Narrator prompt 已经写明：

```text
只能根据输入的规则结算结果写叙事反馈；
不得添加新的状态变化、物品转移、开门结果或 NPC 知识；
accepted=false 时要明确行动被规则拦截。
```

建议补充：

```text
Only describe events and state changes present in rule_result/events.
Do not imply hidden consequences, hidden knowledge, inventory changes, relationship changes, or quest progress unless they are explicitly present in events.
If the action was rejected, describe the rejection as a world rule or current-state limitation, not as model inability.
```

目的：

```text
Narrator 只能展示 EventLog / RuleEngine 已确认事实，不能创造新事实。
```

---

## 6. MemoryAwareDialogue Prompt 修复建议

当前 prompt 已经正确要求：

```text
只能使用给定 memories 作答；
不要读取或猜测 canonical 世界真相；
没有答案就说不知道。
```

建议补充：

```text
If a memory has truth_scope="rumor", phrase it as rumor: "我听说..." / "传闻...".
If confidence is low, phrase uncertainty: "我不太确定...".
Do not present npc/faction/rumor memory as canonical truth.
Do not invent memories, motives, or world facts not present in memories.
```

目的：

```text
让 NPC 对话体现 belief / rumor / uncertainty，避免把传闻固化成真相。
```

---

## 7. ActionParser Prompt 修复建议

当前 ActionParser prompt 已经正确要求：

```text
只输出 JSON；
必须从 affordances 中选择当前可用 action_id 和 target_id；
不要决定合法性，RuleEngine 会裁判。
```

建议补充：

```text
If no affordance matches the player's input, return confidence <= 0.2 and do not invent action_id.
Never output an action_id that is not present in affordances.
If the target is ambiguous, prefer lower confidence instead of inventing a target_id.
```

同时建议后续逐步移除正式游戏路径对 `LEGACY_ACTION_IDS` 的依赖：

```text
动态小世界中，action_id 应该来自当前 WorldSpec / AffordanceEngine，而不是固定 legacy action 表。
```

---

## 8. LLMExtractor Prompt 修复建议

当前 LLMExtractor 仍基于固定 `ALLOWED_ACTION_IDS`，适合旧 PoC，但和动态 WorldSpec 不完全一致。

短期：保留为旧日志抽取 PoC。

中期新增：

```text
DynamicActionExtractor
```

输入：

```text
world_id
player text
current affordances
current action_templates
known entities
state summary
```

输出：

```json
{
  "action_id": "...",
  "target_id": "...",
  "args": {},
  "confidence": 0.0,
  "evidence_span": [0, 1]
}
```

prompt 原则：

```text
只从当前 affordances/action_templates 中选择；
不决定 canonical；
不发明 action_id；
不发明实体；
RuleEngine 仍是最终裁判。
```

---

## 9. 优先级

### P0：立即修 WorldSpec prompt 完整字段契约

```text
scale exactly small_dense
character.goals schema
tension.description
background_lore list[str]
final self-check
```

这是当前模型生成失败的直接原因。

### P1：补 WorldSpec 其他结构示例与 Validator preflight

```text
faction schema
resource schema
initial_state schema
initial_memory shape
对应正反例与 preflight issue
```

### P2：强化叙事与记忆 prompt

```text
Narrator event-only constraint
MemoryAwareDialogue rumor/confidence-aware phrasing
ActionParser no-invention rule
```

### P3：动态化旧 LLMExtractor

```text
ALLOWED_ACTION_IDS -> current affordances/action_templates
```

这应放在动态小世界 play layer 稳定后推进。

---

## 10. Codex 开发任务

可以按以下任务执行：

```text
LP-01 修改 worldspec_prompt_templates.py，补完整 WorldSpec 字段契约。
LP-02 新增 character goal / tension / faction / resource / initial_state / background_lore 正反例。
LP-03 在 WorldSpec prompt 中增加 final self-check。
LP-04 强化 WorldSpecNormalizer：background_lore string -> list；tension summary/title -> description。
LP-05 强化 WorldSpecValidator preflight：goal/tension/background_lore/faction/resource/initial_state 等结构错误。
LP-06 强化 Narrator prompt，禁止暗示 events 中没有的后果。
LP-07 强化 MemoryAwareDialogue prompt，要求 rumor/confidence-aware 表达。
LP-08 强化 ActionParser prompt，禁止发明 affordances 外 action_id。
LP-09 增加测试覆盖以上 prompt 内容和 validator issue。
```

---

## 11. 验收标准

完成后，至少满足：

```text
1. build_full_worldspec_prompt 中明确包含 scale exactly small_dense。
2. prompt 中包含 character goal 正例，且有 goal_id / priority。
3. prompt 中包含 tension 正例，且有 description。
4. prompt 中包含 background_lore list[str] 正反例。
5. prompt 中包含 final self-check。
6. Validator 能明确拒绝 goals 字符串、缺 description 的 tension、background_lore 字符串、resource/initial_state 字符串。
7. Narrator prompt 明确只描述 events/rule_result 已发生事实。
8. Memory prompt 明确 rumor / low confidence 的表达方式。
9. ActionParser prompt 明确不得发明 affordances 外 action_id。
10. 所有新增测试通过。
```

一句话：

> 当前提示词的主问题不是协议格式，也不是“严格 JSON”不够，而是 WorldSpec 字段契约还不完整。先补完整字段契约和 final self-check，再继续实测模型生成质量。
