# Beta 2：WorldSpec 小世界生成器开发方案

## 1. 方案目标

本方案用于在当前 `game-world-kg` 仓库已有能力之上，开发 **WorldSpec 小世界生成器**。

目标链路：

```text
玩家输入一个世界想法
→ 系统生成可验证的 WorldSpec
→ WorldSpec 编译成 Bootstrap Events
→ SQLite EventLog 写入世界真值
→ Kuzu 投影世界结构图
→ Chroma 投影背景、证据与初始记忆
→ 玩家进入小世界试玩
→ NPC 基于目标、记忆、资源、关系与规则自运行
```

核心目标不是生成无限开放世界，而是生成一个：

```text
小而密
可运行
可回放
可解释
可试玩 30～100 回合
NPC 有目标与记忆
任务从世界矛盾中自然出现
```

的小型世界。

---

## 2. 对前一版思路的审查

### 2.1 符合研究报告的部分

前一版思路中，以下判断是正确的，必须保留：

#### 1. LLM 只生成候选，不能直接建立世界真值

正确链路是：

```text
LLM → WorldSpecCandidate
Validator → accept / reject / repair
BootstrapCompiler → Bootstrap Events
SQLite EventLog → source of truth
```

而不是：

```text
LLM → 直接写 DB / 直接写 Kuzu / 直接写 canonical state
```

这符合研究报告中的原则：

```text
SQLite 是真值源
Kuzu / Chroma 是物化视图和检索层
LLM 只负责候选抽取、叙事、补全
```

#### 2. WorldSpec 不是存档，Bootstrap Events 才是世界建立过程

WorldSpec 只是蓝图，不是世界真值。

真正的世界创建必须进入事件日志：

```text
WORLD_CREATED
CREATE_LOCATION
CREATE_ENTITY
CREATE_ITEM
CREATE_FACTION
CREATE_RULE
CREATE_ACTION_TEMPLATE
SET_STATE
ADD_MEMORY
ADD_TENSION
START_QUEST
```

这样生成出来的世界才能 replay、rollback、debug、explain。

#### 3. 世界生成必须走 Validator

LLM 生成的 WorldSpec 必须经过：

```text
schema 校验
引用完整性校验
地图连通性校验
action template 可编译性校验
quest / tension 可追溯性校验
scope / memory 隔离校验
```

否则生成的世界可能“设定好看但跑不起来”。

#### 4. NPC 自运行必须受 RuleEngine 约束

NPC 不能直接根据 LLM 输出改变世界。

正确链路：

```text
NPC goal + memory + resource + relation + tension
→ candidate action
→ RuleEngine validate
→ NPC_ACTION event
→ StateProjector / KuzuProjector / ChromaProjector
```

#### 5. 小世界策略是正确的

第一版世界生成器不应该追求无限大世界，而应该生成：

```text
6～10 个地点
5～8 个 NPC
8～15 个物品
2～4 个势力
8～15 个 ActionTemplate
3～5 条 Tension
2～4 个初始 Quest
```

目标是“可运行的小而密世界”，不是一次性生成大地图。

---

### 2.2 需要修正和收敛的部分

前一版思路还需要收敛以下几点：

#### 1. 不能跳过当前 Beta 1 记忆治理要求

当前仓库已经进入 NPC 对话长期 Memory Graph 阶段。

在 World Generator 开始前，至少要保证：

```text
SQLite EventLog 是真值源
Kuzu native graph path 可用
Chroma scoped retrieval 可用
conversation log 不可变保存
NPC 不能越权读取私有记忆
rumor / belief / canonical 不混淆
```

如果这些没稳定，世界生成器会生成很多初始 NPC 和记忆，但无法保证长期运行不污染 canonical。

#### 2. WorldSpec 不能包含任意自由文本规则

WorldSpec 中的规则必须能落到现有 RuleEngine 的 predicate/effect。

错误设计：

```json
{"rule": "修仙世界应该很危险，玩家要谨慎"}
```

正确设计：

```json
{
  "rule_id": "dangerous_back_mountain",
  "kind": "state_gate",
  "preconditions": [
    {"type": "state_equals", "entity": "back_mountain", "attr": "danger_level", "value": "high"}
  ],
  "effects": [
    {"type": "delta_resource", "entity": "player", "attr": "health", "delta": -1}
  ]
}
```

#### 3. NPC Planner 第一版必须短程、低风险、可解释

不要一上来做复杂多步 Tree-of-Thought 或长程自主代理。

第一版只做：

```text
observe
move_to
talk_to
trade
spread_rumor
request_help
inspect
patrol
```

每次 tick 最多选择 1 个 action。

#### 4. Drama Manager 不应先于可运行世界

Drama Manager 很重要，但应该在世界能稳定运行后再做。

当前阶段只做轻量：

```text
TensionScanner
QuestGenerator
PlayerInterestTracker v0
```

不要过早做复杂导演系统。

---

## 3. 严格遵循的项目原则

World Generator 必须遵循当前项目研究报告与代码架构的这些原则：

```text
1. EventLog 是 source of truth。
2. Kuzu / Chroma 不是真值源，只是投影和检索层。
3. LLM 只生成候选 WorldSpec / candidate action / narration。
4. 所有世界变化必须写成 EventRecord。
5. canonical / npc / faction / rumor / candidate 必须分层。
6. NPC 只能基于自己可知记忆、目标、资源、关系行动。
7. ActionTemplate 必须能编译到 Predicate + Effect。
8. Quest 必须从 Tension 生成，并能追溯 evidence。
9. 世界必须支持 replay / rebuild / explain。
10. Evaluation 必须覆盖生成质量、可运行性、一致性和污染率。
```

---

## 4. 总体架构

```text
User World Idea
    ↓
WorldIntentExtractor
    ↓
WorldSpecGenerator
    ↓
WorldSpecValidator
    ↓
WorldSpecRepairer 可选
    ↓
BootstrapCompiler
    ↓
SQLite EventLog Transaction
    ↓
Outbox
    ↓
StateProjector / KuzuProjector / ChromaProjector
    ↓
Playable Runtime
    ↓
AffordanceEngine / RuleEngine / NPCPlanner / TensionScanner / QuestGenerator
```

关键关系：

```text
WorldSpec 是候选蓝图
Bootstrap Events 是创建过程
SQLite EventLog 是真值
Kuzu 是结构化世界图
Chroma 是背景与记忆检索
RuleEngine 是合法性裁判
NPCPlanner 是自运行调度器
Narrator 是展示层
```

---

## 5. WorldSpec 模型设计

## 5.1 WorldSpec 顶层结构

```json
{
  "world_id": "demo_cultivation_town",
  "title": "青木镇外门风波",
  "genre": "cultivation",
  "theme": "外门弟子成长与后山异常",
  "starting_area": "greenwood_town",
  "scale": "small_dense",
  "player_start": {
    "character_id": "player",
    "location_id": "town_gate"
  },
  "ontology_extensions": [],
  "locations": [],
  "characters": [],
  "items": [],
  "factions": [],
  "resources": [],
  "rules": [],
  "action_templates": [],
  "initial_states": [],
  "initial_memories": [],
  "initial_tensions": [],
  "initial_quests": [],
  "background_lore": []
}
```

---

## 5.2 LocationSpec

```json
{
  "id": "herb_shop",
  "stable_key": "herb_shop",
  "name": "药铺",
  "description": "青木镇唯一的药铺，最近因为灵草短缺而生意紧张。",
  "location_type": "shop",
  "connects_to": ["market"],
  "tags": ["trade", "healing", "quest_hub"]
}
```

约束：

```text
每个 location 必须有 stable_key。
至少一个 location 是 player_start。
地点图必须整体连通。
地点数量第一版限制为 6～10。
```

---

## 5.3 CharacterSpec

```json
{
  "id": "herb_master",
  "stable_key": "herb_master",
  "name": "药铺老板许青",
  "role": "herb_shop_owner",
  "start_location": "herb_shop",
  "faction_id": "townsfolk",
  "goals": [
    {"goal_id": "restore_herb_supply", "priority": 0.9},
    {"goal_id": "avoid_personal_risk", "priority": 0.5}
  ],
  "personality": {
    "cautious": 0.7,
    "helpful": 0.6
  },
  "initial_beliefs": [
    "后山灵草变少可能和妖兽异常有关。"
  ]
}
```

约束：

```text
NPC 必须有 start_location。
NPC goals 必须可被 Planner 使用。
NPC belief 只进入 npc/faction scope，不进入 canonical。
NPC 数量第一版限制为 5～8。
```

---

## 5.4 ItemSpec

```json
{
  "id": "outer_token",
  "stable_key": "outer_token",
  "name": "外门令牌",
  "item_type": "permit",
  "owner_id": "player",
  "tags": ["identity", "access"]
}
```

约束：

```text
item 必须有 owner_id 或 location_id。
任务关键物品必须存在。
物品数量第一版限制为 8～15。
```

---

## 5.5 FactionSpec

```json
{
  "id": "outer_sect",
  "stable_key": "outer_sect",
  "name": "青木宗外门",
  "faction_type": "sect",
  "goals": ["maintain_order", "train_disciples"],
  "relations": [
    {"target": "townsfolk", "relation": "protects", "value": 0.6}
  ]
}
```

约束：

```text
faction relation 只作为初始图谱关系。
具体态度变化仍由事件驱动。
```

---

## 5.6 ActionTemplateSpec

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
    {"type": "same_location", "a": "player", "b": "$target"}
  ],
  "effects": [
    {"type": "add_conversation_event", "actor": "player", "target": "$target", "topic": "$topic"}
  ],
  "risk": "low"
}
```

约束：

```text
preconditions 必须全部来自支持的 Predicate。
effects 必须全部来自支持的 Effect。
不得包含任意自由执行代码。
```

---

## 5.7 TensionSpec

```json
{
  "id": "herb_shortage",
  "tension_type": "resource_shortage",
  "description": "药铺缺少灵草，镇民买药困难。",
  "affected_entities": ["herb_shop", "spirit_herb", "herb_master"],
  "evidence": [
    {"type": "state", "entity": "herb_shop", "attr": "herb_stock", "value": "low"}
  ],
  "suggested_actions": ["ask_about_topic", "investigate_location"]
}
```

约束：

```text
Tension 必须引用存在实体。
Tension 必须有 evidence。
Tension 不能是纯文案。
```

---

## 5.8 QuestSpec

```json
{
  "id": "investigate_back_mountain",
  "title": "调查后山异常",
  "issuer_id": "sect_senior",
  "tension_id": "monster_abnormal",
  "objectives": [
    {"type": "visit_location", "target": "back_mountain"},
    {"type": "collect_evidence", "target": "monster_trace"}
  ],
  "rewards": [
    {"type": "delta_resource", "entity": "player", "attr": "sect_contribution", "delta": 5}
  ],
  "failure_consequences": [
    {"type": "increase_tension", "target": "monster_abnormal", "delta": 1}
  ]
}
```

约束：

```text
quest 必须绑定 tension_id。
issuer 必须存在。
objective target 必须存在或可由规则生成。
reward 必须可执行。
```

---

## 6. WorldSpecValidator 设计

Validator 分 8 层。

### 6.1 Schema 校验

检查字段类型、必填字段、枚举值。

### 6.2 Stable Key 校验

```text
stable_key 唯一
ID 不重复
引用不悬空
```

### 6.3 地图连通性校验

```text
所有地点必须从 player_start 可达。
不存在孤岛地点。
```

### 6.4 实体归属校验

```text
NPC 必须有 start_location。
Item 必须有 owner 或 location。
Faction relation target 必须存在。
```

### 6.5 ActionTemplate 可编译性校验

```text
所有 Predicate 类型必须支持。
所有 Effect 类型必须支持。
引用变量必须在 arg_schema / selector 中存在。
```

### 6.6 Tension 可追溯性校验

```text
affected_entities 全部存在。
evidence 不为空。
suggested_actions 必须对应 action_templates。
```

### 6.7 Quest 合法性校验

```text
issuer 存在。
tension_id 存在。
objectives 可执行。
rewards 可执行。
```

### 6.8 小而密约束校验

```text
locations: 6～10
characters: 5～8
items: 8～15
factions: 2～4
action_templates: 8～15
tensions: 3～5
quests: 2～4
```

---

## 7. BootstrapCompiler 设计

WorldSpec 不能直接写 DB，必须编译成事件。

### 7.1 编译顺序

```text
1. WORLD_CREATED
2. CREATE_FACTION
3. CREATE_LOCATION
4. CONNECT_LOCATION
5. CREATE_ENTITY / CREATE_CHARACTER
6. CREATE_ITEM
7. CREATE_RULE
8. CREATE_ACTION_TEMPLATE
9. SET_STATE
10. ADD_MEMORY
11. ADD_TENSION
12. START_QUEST
13. WORLD_BOOTSTRAP_COMPLETED
```

### 7.2 事件写入方式

必须在一个 SQLite transaction 中完成：

```text
BEGIN
append all bootstrap events
append state_deltas
append outbox rows
COMMIT
```

### 7.3 幂等策略

每个 world bootstrap 必须有：

```text
world_id
world_spec_hash
bootstrap_id
idempotency_key
```

如果同一 `world_id + world_spec_hash` 已成功 bootstrap，则不重复写入。

---

## 8. 三存储投影设计

### 8.1 SQLite

存：

```text
events
state_deltas
states
source_texts
evidence_refs
world_specs
bootstrap_runs
```

新增建议表：

```sql
CREATE TABLE IF NOT EXISTS world_specs (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    validation_report_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bootstrap_runs (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    world_spec_id TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    event_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
```

### 8.2 Kuzu

投影：

```text
Location graph
Character graph
Item ownership/location
Faction relations
ActionTemplate nodes
Rule nodes
Tension nodes
Quest nodes
Event causality
Memory nodes
```

核心查询：

```text
current_location_neighbors
entities_near_player
tensions_affecting_entity
quests_from_tension
action_templates_for_location
npc_goal_context
```

### 8.3 Chroma

投影 collections：

```text
world_sources
world_memories
world_events
world_rules
world_quests
world_specs
```

存入：

```text
world background
location description
NPC initial memories
faction doctrine
rule explanation
quest background
tension description
```

Chroma 只用于召回，不决定 canonical。

---

## 9. NPC Planner 设计

第一版采用轻量 GOAP / BDI 混合模型。

### 9.1 NPC 状态输入

```text
current_location
resources
relations
active_goals
known_memories
known_rumors
visible_tensions
available_actions
```

### 9.2 NPC Goal

```json
{
  "goal_id": "restore_herb_supply",
  "priority": 0.9,
  "desired_state": {
    "entity": "herb_shop",
    "attr": "herb_stock",
    "value": "normal"
  },
  "risk_tolerance": 0.3
}
```

### 9.3 Planner 流程

```text
1. 读取 NPC 当前状态
2. Chroma scoped recall 召回该 NPC 可知记忆
3. Kuzu 查询相关 tension / quest / relation
4. AffordanceEngine 生成 NPC 可行动作
5. 根据 goal relevance / risk / cost / relation impact 打分
6. RuleEngine 校验最高分 action
7. 写 NPC_ACTION event
8. Projector 更新状态、图谱和记忆
```

### 9.4 第一版行动集合

```text
move_to
talk_to
observe
inspect
trade
spread_rumor
request_help
patrol
report_to_faction
```

### 9.5 Planner 限制

```text
每个 tick 每个 NPC 最多 1 个 action。
每轮最多激活 1～3 个 NPC。
低优先级 NPC 可跳过。
高风险 action 需要更高 goal priority。
```

---

## 10. Tension / Quest / Drama 分层

### 10.1 TensionScanner

扫描世界结构矛盾：

```text
resource_shortage
locked_location
rumor_unresolved
trust_below_threshold
npc_goal_blocked
hostility_rising
quest_dependency_missing
```

### 10.2 QuestGenerator

从 tension 生成任务候选。

要求：

```text
quest 必须有 tension_id。
quest 必须有 evidence。
quest objective 必须可执行。
quest reward 必须可兑现。
```

### 10.3 Drama Manager v0

不要一开始做复杂导演。

第一版只做：

```text
Tension priority scoring
Player interest tracking
Foreground event selection
```

输入：

```text
玩家最近访问地点
玩家最近对话 NPC
玩家最近接受任务
高 salience memory
高风险 tension
```

输出：

```text
哪些 tension 应该被前台展示
哪些 NPC 应该主动找玩家
哪些 quest 应该进入推荐列表
```

---

## 11. API 设计

新增 API：

```text
POST /v1/worldspec/generate
POST /v1/worldspec/validate
POST /v1/worldspec/repair
POST /v1/worldspec/bootstrap
GET  /worlds/{world_id}/worldspec
POST /worlds/{world_id}/tick
POST /worlds/{world_id}/npc/{npc_id}/tick
GET  /worlds/{world_id}/planner/npcs/{npc_id}/context
GET  /worlds/{world_id}/tensions
GET  /worlds/{world_id}/drama/foreground
GET  /worlds/{world_id}/evaluation/worldgen
```

---

## 12. 开发阶段

## Phase 1：WorldSpec Schema + Validator

目标：建立世界蓝图合同。

任务：

```text
1. 新增 worldspec.py
2. 定义 WorldSpec / LocationSpec / CharacterSpec / ItemSpec / FactionSpec
3. 定义 ActionTemplateSpec / TensionSpec / QuestSpec
4. 实现 WorldSpecValidator
5. 增加 world_specs 表
6. 增加 /v1/worldspec/validate
```

验收：

```text
- 修仙/海洋/村庄三个 sample spec 可通过校验
- 悬空引用会失败
- 不连通地图会失败
- 非法 action predicate/effect 会失败
```

---

## Phase 2：WorldSpecGenerator + Repairer

目标：从玩家自然语言生成可校验 spec。

任务：

```text
1. WorldIntentExtractor
2. WorldSpecGenerator prompt
3. 输出严格 JSON
4. 生成后自动 validate
5. validate 失败进入 repair loop
6. 最多 repair 2 次
7. 失败则返回 validation_report
```

验收：

```text
- 输入一句世界想法能生成 WorldSpecCandidate
- 不直接写世界
- 修复后仍不合法则拒绝
- 所有 LLM 输出都保存 source_text / candidate 记录
```

---

## Phase 3：BootstrapCompiler

目标：WorldSpec 事件化。

任务：

```text
1. 新增 bootstrap.py
2. WorldSpec → BootstrapEventDrafts
3. 支持 WORLD_CREATED / CREATE_* / SET_STATE / ADD_MEMORY / ADD_TENSION / START_QUEST
4. SQLite transaction 写入事件
5. 写 bootstrap_runs
6. 写 outbox
7. 支持 idempotency
```

验收：

```text
- demo_cultivation_town spec 能 bootstrap 成 world
- replay 后世界一致
- Kuzu / Chroma rebuild 后可查询
```

---

## Phase 4：ActionTemplate Runtime

目标：生成世界真的能行动。

任务：

```text
1. ActionTemplateCompiler
2. PredicateEvaluator
3. EffectExecutor
4. AffordanceEngine 从 action_templates 生成动作
5. RuleEngine 执行模板 effects
6. 替换硬编码世界 action
```

验收：

```text
- WorldSpec 生成的 action template 可运行
- move_to / talk_to / inspect / trade / ask_about_topic 可用
- 非法动作被拒绝
- 合法动作写事件
```

---

## Phase 5：NPC Planner Tick

目标：NPC 自运行第一版。

任务：

```text
1. npc_planner.py
2. NPCGoal model
3. PlannerContext builder
4. Chroma scoped memory recall
5. Kuzu tension/relation query
6. Candidate action scoring
7. RuleEngine validation
8. NPC_ACTION event
9. /worlds/{world_id}/tick
```

验收：

```text
- 运行 30 ticks 不崩
- NPC action 都经过 RuleEngine
- NPC 不越权读取私有记忆
- NPC 行动能改变 relation / memory / tension
```

---

## Phase 6：Tension / Quest / Drama v0

目标：世界产生可玩的局势。

任务：

```text
1. TensionScanner 泛化
2. QuestGenerator 从 tension 生成任务
3. QuestValidator
4. PlayerInterestTracker
5. DramaManager v0
6. foreground tensions API
```

验收：

```text
- 每个 quest 有 tension_id / evidence
- drama foreground 能推荐 1～3 个前台局势
- 玩家行动影响 tension priority
```

---

## Phase 7：Evaluation Harness

目标：可验证小世界生成质量。

指标：

```text
worldspec_valid_rate
repair_success_rate
bootstrap_replay_equivalence
kuzu_rebuild_consistency
chroma_scoped_retrieval_accuracy
turns_playable
invalid_action_rate
npc_privileged_knowledge_rate
quest_traceability_rate
canonical_contamination_rate
```

验收阈值：

```text
worldspec_valid_rate >= 80% for constrained prompts
bootstrap_replay_equivalence = 100%
kuzu_rebuild_consistency = 100%
canonical_contamination_rate = 0%
npc_privileged_knowledge_rate <= 5%
quest_traceability_rate >= 90%
turns_playable >= 30
```

---

## 13. 推荐 Codex Issue 顺序

### WG-01 Add WorldSpec schema and validator

### WG-02 Add WorldSpec generator and repair loop

### WG-03 Implement WorldSpec to Bootstrap Events compiler

### WG-04 Add bootstrap transaction and idempotent world creation

### WG-05 Implement ActionTemplate compiler and template runtime

### WG-06 Implement NPC planner tick loop

### WG-07 Implement generalized TensionScanner and QuestGenerator

### WG-08 Add DramaManager v0 and PlayerInterestTracker

### WG-09 Add worldgen evaluation suite

---

## 14. 不允许偏离的点

开发过程中禁止：

```text
1. WorldSpec 直接写 Kuzu。
2. WorldSpec 直接写 Chroma 后当真值用。
3. LLM 直接修改 canonical state。
4. NPC Planner 绕过 RuleEngine。
5. Quest 没有 tension/evidence。
6. ActionTemplate 使用不可验证自由文本 effect。
7. Drama Manager 直接改世界。
8. Chroma recall 直接当 canonical fact。
9. 生成无限地点 / 无限 NPC。
10. 跳过 replay / rebuild 测试。
```

---

## 15. 完成定义

Beta 2 完成时，必须能演示：

```text
1. 玩家输入：我想玩一个修仙小镇，主角刚入外门，后山妖兽异常。
2. 系统生成 WorldSpec。
3. Validator 通过。
4. BootstrapCompiler 编译成事件。
5. SQLite EventLog 写入世界真值。
6. Kuzu 查询到地点、NPC、任务、tension 结构。
7. Chroma 查询到世界背景和 NPC 初始记忆。
8. 玩家进入世界后有 5 个以上合法可行动作。
9. NPC tick 后世界状态发生合理变化。
10. 玩家/NPC 连续运行 30～100 回合。
11. replay / rebuild 后状态一致。
12. canonical 未被 rumor / hallucination 污染。
13. 每个 quest 都能追溯到 tension 和 evidence。
```

一句话完成标准：

> 玩家输入一个世界想法，系统生成一个小而密、可回放、可解释、可试玩、可自运行的小世界。
