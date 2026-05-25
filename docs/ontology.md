# Game World KG 本体与版本化设计

## 1. 设计目标

本体层用于回答：游戏世界里有哪些东西、它们如何被分类、如何建立关系、如何随时间变化。

本项目不把知识图谱当成静态百科，而是当成**运行时世界结构层**。因此本体必须同时支持：

- 稳定身份
- 时间版本
- 事件溯源
- 主观记忆
- 可供性推理
- 规则验证
- 状态回放

核心原则：

```text
Ontology first, KG second, LLM extraction third.
```

也就是说，先定义类型系统，再构建图谱，最后才让 LLM 在 Schema 约束下抽取候选事实。

---

## 2. 通用实体类型

### 2.1 Character

角色、玩家、NPC、怪物、代理实体都属于 Character。

必需字段：

```json
{
  "id": "char_guard_alos_v1",
  "stable_key": "guard_alos",
  "world_id": "demo_world",
  "entity_type": "Character",
  "version": 1,
  "name": "守卫阿洛斯",
  "archetype": "gate_guard",
  "faction_ids": ["faction_gate_watch"],
  "stats_ref": "state:guard_alos",
  "scope": "canonical",
  "valid_from_turn": 0,
  "valid_to_turn": null,
  "recorded_at": "2026-05-25T00:00:00Z"
}
```

关键关系：

```text
MEMBER_OF
OWNS
LOCATED_IN
KNOWS
REMEMBERS
TRUSTS
OPPOSES
```

版本策略：

- 身份稳定，`stable_key` 不变。
- 位置、阵营、拥有权用版本化边表示。
- 心理状态与记忆不直接覆盖 canonical 世界真值。

---

### 2.2 Location

地点、房间、区域、世界分区、地图节点都属于 Location。

必需字段：

```json
{
  "id": "loc_village_gate_v1",
  "stable_key": "village_gate",
  "world_id": "demo_world",
  "entity_type": "Location",
  "version": 1,
  "name": "村口",
  "loc_type": "outdoor_gate",
  "parent_id": null,
  "scope": "canonical",
  "valid_from_turn": 0,
  "valid_to_turn": null
}
```

关键关系：

```text
CONNECTS_TO
CONTAINS
CONTROLLED_BY
HAS_RULE
HAS_AFFORDANCE
```

版本策略：

- 空间拓扑通常慢变。
- 占用、封锁、危险状态通过 State/Event 更新。

---

### 2.3 Item

物品、装备、工具、消耗品、任务物品都属于 Item。

必需字段：

```json
{
  "id": "item_pass_token_v1",
  "stable_key": "pass_token",
  "world_id": "demo_world",
  "entity_type": "Item",
  "version": 1,
  "name": "通行令",
  "item_type": "permit",
  "rarity": "common",
  "stackable": false,
  "scope": "canonical",
  "valid_from_turn": 0,
  "valid_to_turn": null
}
```

关键关系：

```text
OWNED_BY
LOCATED_IN
REQUIRED_BY
REWARD_OF
CAN_OPEN
CAN_USE_ON
```

版本策略：

- 持有者、所在地点高频变化，必须由 Event + StateDelta 驱动。
- 物品定义本身慢变，平衡调整要版本化。

---

### 2.4 Faction

势力、组织、宗门、村庄、商会、队伍都属于 Faction。

必需字段：

```json
{
  "id": "faction_gate_watch_v1",
  "stable_key": "gate_watch",
  "world_id": "demo_world",
  "entity_type": "Faction",
  "version": 1,
  "name": "城门卫队",
  "doctrine": "维护城门秩序",
  "standing_rules": ["rule_gate_access"],
  "scope": "canonical",
  "valid_from_turn": 0,
  "valid_to_turn": null
}
```

关键关系：

```text
ALLIED_WITH
HOSTILE_TO
CONTROLS
ISSUES
EMPLOYS
TRUSTS
OPPOSES
```

版本策略：

- 阵营关系边必须带有效期。
- 势力认知可使用 `scope=faction` 表示，不等于世界真相。

---

### 2.5 Rule

规则、禁令、权限条件、世界法则、站点规则都属于 Rule。

必需字段：

```json
{
  "id": "rule_gate_access_v1",
  "stable_key": "gate_access",
  "world_id": "demo_world",
  "entity_type": "Rule",
  "version": 1,
  "rule_type": "access_control",
  "priority": 100,
  "scope_ref": "loc_iron_gate",
  "expr_ref": "rules.gate_access.validate",
  "enabled": true,
  "valid_from_turn": 0,
  "valid_to_turn": null
}
```

关键关系：

```text
GOVERNS
FORBIDS
ENABLES
MODIFIES
REQUIRES
```

版本策略：

- 图谱只存规则元数据。
- 具体执行体保存在 Rule Engine。
- 规则版本应和规则引擎代码版本同步。

---

### 2.6 Event

事件是世界变化的基本单位，也是回放、审计、回滚的依据。

必需字段：

```json
{
  "event_id": "evt_00042",
  "event_type": "TRANSFER_ITEM",
  "world_id": "demo_world",
  "turn_id": "turn_12",
  "turn_index": 12,
  "participants": ["player", "guard_alos", "pass_token"],
  "causal_parents": ["evt_00038"],
  "state_deltas": [],
  "evidence_refs": []
}
```

关键关系：

```text
CAUSED_BY
TARGETS
CHANGES
ENABLED_BY
PRODUCES
CONSUMES
```

版本策略：

- 事件追加式不可变。
- 不修改历史事件。
- 修正错误时追加 CORRECTION_EVENT 或 REVERT_EVENT。

---

### 2.7 Quest

任务、事件线、目标链都属于 Quest。

必需字段：

```json
{
  "id": "quest_enter_city_v1",
  "stable_key": "enter_city",
  "world_id": "demo_world",
  "entity_type": "Quest",
  "version": 1,
  "title": "进入内城",
  "issuer_id": "guard_alos",
  "objective_graph": ["show_pass_token", "open_gate"],
  "rewards": [],
  "status": "active"
}
```

关键关系：

```text
ISSUED_BY
DEPENDS_ON
TARGETS_RULE
UNLOCKS
REWARDS
FAILS_IF
```

版本策略：

- 任务定义慢变。
- 任务进度通过 Event / State 记录。

---

### 2.8 Ability

技能、天赋、法术、动作能力都属于 Ability。

必需字段：

```json
{
  "id": "ability_pick_lock_v1",
  "stable_key": "pick_lock",
  "entity_type": "Ability",
  "version": 1,
  "name": "撬锁",
  "cost": {"stamina": 1},
  "cooldown": 0,
  "effect_ref": "rules.pick_lock.apply"
}
```

关键关系：

```text
BELONGS_TO
USED_IN
MODIFIES_STATE
ENABLES_ACTION
```

版本策略：

- 技能平衡改动更新版本。
- 历史事件中的旧技能效果不回写。

---

### 2.9 Resource

金币、水、食物、声望、灵气、耐久等数值资源都属于 Resource。

必需字段：

```json
{
  "id": "res_player_gold_v1",
  "owner_id": "player",
  "resource_type": "gold",
  "amount": 10,
  "unit": "coin"
}
```

关键关系：

```text
PRODUCED_BY
CONSUMED_BY
STORED_IN
OWNED_BY
```

版本策略：

- 高频资源使用 ledger delta。
- 不直接覆盖历史库存。
- 当前值由 ledger 投影得到。

---

### 2.10 State

状态快照或状态增量。

必需字段：

```json
{
  "id": "state_iron_gate_locked_t0",
  "subject_id": "iron_gate",
  "turn_id": 0,
  "truth_scope": "canonical",
  "attrs": {
    "locked": true,
    "open": false
  }
}
```

关键关系：

```text
STATE_OF
DERIVED_FROM
```

版本策略：

- 高频数值不污染静态实体。
- State 可以由 Event replay 重建。

---

### 2.11 Action

动作模板，不是单次玩家输入。

必需字段：

```json
{
  "id": "action_show_item_v1",
  "stable_key": "show_item",
  "verb": "show",
  "arg_schema": {
    "actor": "Character",
    "target": "Character",
    "item": "Item"
  },
  "validator_ref": "rules.show_item.validate",
  "effect_template": "rules.show_item.effects"
}
```

关键关系：

```text
CAN_TARGET
REQUIRES
PRODUCES
ENABLES
```

版本策略：

- 行为模板版本化。
- Affordance 层绑定当前可用动作。

---

### 2.12 Affordance

当前对象、场景、角色可以触发的行动可能性。

必需字段：

```json
{
  "id": "aff_show_pass_to_guard_t3",
  "subject_type": "Character",
  "action_id": "action_show_item_v1",
  "target_id": "guard_alos",
  "preconditions": ["player_has_pass_token", "same_location"],
  "effects": ["guard_inspects_token"],
  "risk": "low",
  "score": 0.9
}
```

关键关系：

```text
ENABLES_ACTION
REQUIRES
MAY_PRODUCE
CONSTRAINED_BY
```

版本策略：

- 每回合可重算。
- 可缓存为短期派生图。
- 不是世界真值源。

---

### 2.13 Memory

角色记忆、误记、传闻、信念。

必需字段：

```json
{
  "id": "mem_guard_player_showed_token",
  "owner_id": "guard_alos",
  "source_event_id": "evt_00042",
  "salience": 0.8,
  "valence": 0.2,
  "truth_status": "observed",
  "last_recalled_turn": null,
  "scope": "npc"
}
```

关键关系：

```text
ABOUT
REMEMBERS
MISREMEMBERS
HEARD_RUMOR_OF
```

版本策略：

- 与世界真值分层。
- 支持衰减、误记、谣言共存。

---

## 3. Scope 分层

所有实体、关系、状态、记忆都可以带 scope。

```text
canonical：世界真相
player：玩家已知
npc：某个 NPC 的主观记忆
faction：某个势力认知
rumor：传闻、误解、未证实信息
```

示例：

```text
canonical：玩家没有偷钥匙
npc.guard：守卫怀疑玩家知道钥匙下落
rumor：村里传闻玩家和盗贼有联系
```

规则：

- `rumor` 不能直接覆盖 `canonical`。
- `npc` 记忆只能影响该 NPC 的行为和对话。
- `faction` 认知可以驱动势力行动，但不等于世界真相。
- `canonical` 的修改必须来自权威事件、规则判定或人工确认。

---

## 4. 稳定身份与版本策略

### 4.1 stable_key

每个实体有一个稳定身份：

```text
stable_key = 世界内长期不变的逻辑身份
```

示例：

```text
guard_alos
village_gate
pass_token
iron_gate
```

即使实体属性变化，`stable_key` 不变。

### 4.2 version

实体和关系有版本号：

```text
version = 1, 2, 3...
```

每次实体核心属性或关系语义变化，新增版本，不覆盖旧版本。

### 4.3 valid_from_turn / valid_to_turn

表示游戏内有效时间。

示例：

```text
守卫 --TRUSTS--> 玩家，value=2，有效 turn 1-5
守卫 --TRUSTS--> 玩家，value=5，有效 turn 6-null
```

### 4.4 recorded_at

表示系统记录时间。

这和游戏内时间不同。用于调试、审计和数据迁移。

### 4.5 expected_version

写入更新时可以带 expected_version，防止并发覆盖。

---

## 5. 冲突处理策略

### 5.1 身份冲突

当两个实体可能指向同一对象时：

1. 先做别名和上下文消歧。
2. 置信度不足时新建临时实体。
3. 后续用 MERGE_ENTITY 事件合并。

### 5.2 事实冲突

不直接覆盖。

处理方式：

```text
canonical 冲突 → 进入审查或追加 CORRECTION_EVENT
npc 记忆冲突 → 保留为主观误记
rumor 冲突 → 保留为并行传闻
```

### 5.3 并发冲突

权威级别：

```text
系统事件 > 设计器编排 > 规则推导 > 玩家/NPC 自然语言陈述 > 谣言
```

### 5.4 低置信抽取

低置信结果不进入 canonical。

可进入：

```text
candidate
npc memory
rumor
review queue
```

---

## 6. 最小 JSON Schema 契约

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GameWorldKG Core",
  "type": "object",
  "$defs": {
    "EvidenceRef": {
      "type": "object",
      "required": ["source_id", "span", "extractor", "confidence"],
      "properties": {
        "source_id": {"type": "string"},
        "span": {
          "type": "array",
          "items": {"type": "integer"},
          "minItems": 2,
          "maxItems": 2
        },
        "chunk_id": {"type": "string"},
        "extractor": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
      }
    },
    "EntityVersion": {
      "type": "object",
      "required": [
        "id", "stable_key", "world_id", "entity_type", "version",
        "valid_from_turn", "properties", "scope", "confidence"
      ],
      "properties": {
        "id": {"type": "string"},
        "stable_key": {"type": "string"},
        "world_id": {"type": "string"},
        "entity_type": {"type": "string"},
        "version": {"type": "integer", "minimum": 1},
        "valid_from_turn": {"type": "integer", "minimum": 0},
        "valid_to_turn": {"type": ["integer", "null"]},
        "recorded_at": {"type": "string", "format": "date-time"},
        "scope": {"enum": ["canonical", "player", "npc", "faction", "rumor"]},
        "properties": {"type": "object"},
        "source_event_id": {"type": ["string", "null"]},
        "evidence_refs": {
          "type": "array",
          "items": {"$ref": "#/$defs/EvidenceRef"}
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
      }
    },
    "RelationVersion": {
      "type": "object",
      "required": [
        "id", "src", "rel_type", "dst", "version",
        "valid_from_turn", "scope", "confidence"
      ],
      "properties": {
        "id": {"type": "string"},
        "src": {"type": "string"},
        "rel_type": {"type": "string"},
        "dst": {"type": "string"},
        "version": {"type": "integer", "minimum": 1},
        "valid_from_turn": {"type": "integer", "minimum": 0},
        "valid_to_turn": {"type": ["integer", "null"]},
        "scope": {"enum": ["canonical", "player", "npc", "faction", "rumor"]},
        "properties": {"type": "object"},
        "source_event_id": {"type": ["string", "null"]},
        "evidence_refs": {
          "type": "array",
          "items": {"$ref": "#/$defs/EvidenceRef"}
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
      }
    },
    "EventRecord": {
      "type": "object",
      "required": ["event_id", "event_type", "turn_id", "participants", "state_deltas"],
      "properties": {
        "event_id": {"type": "string"},
        "event_type": {"type": "string"},
        "turn_id": {"type": "integer"},
        "participants": {"type": "array", "items": {"type": "string"}},
        "causal_parents": {"type": "array", "items": {"type": "string"}},
        "state_deltas": {"type": "array", "items": {"type": "object"}},
        "evidence_refs": {
          "type": "array",
          "items": {"$ref": "#/$defs/EvidenceRef"}
        }
      }
    }
  }
}
```

---

## 7. MVP 简化建议

第一版实现时不要全部复杂化。

必须保留：

```text
stable_key
version
valid_from_turn
valid_to_turn
scope
confidence
source_event_id
evidence_refs
```

可以后置：

```text
recorded_at 的复杂查询
expected_version 并发控制
实体合并工作流
人工审查队列
```

但字段要先留出来，避免后续迁移困难。
