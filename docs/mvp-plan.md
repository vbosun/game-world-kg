# Game World KG 本地 MVP 方案

## 1. 项目目标

构建一个**事件溯源驱动的动态游戏世界知识图谱内核**，验证 AI 生成式游戏世界能否做到：

- 状态一致
- NPC 不失忆
- 行动可验证
- 可行动作由世界状态推导
- 任务可从世界矛盾中自然生长
- 世界状态可回放、回滚、审计

一句话架构：

```text
Event Log 是真值源
WorldGraph 是结构化世界视图
Rule Engine 是合法性裁判
Vector Memory 是长文本证据库
LLM 是叙事、抽取、对话和补全器
```

---

## 2. MVP 不做什么

第一阶段不追求完整游戏，而是验证底层闭环。

暂不做：

- 复杂 UI
- 大地图
- 战斗系统
- 多题材世界生成
- 完整 NPC Agent
- Neo4j / Qdrant / Drools 全家桶
- 自动小说导入
- 长篇剧情生成

第一版重点是：

> 玩家行动 → 结构化 action → 规则判定 → 事件追加 → 状态投影 → 图谱更新 → 记忆更新 → affordance 变化 → LLM 叙事。

---

## 3. MVP 技术栈

推荐本地轻量栈：

```text
Python 3.11+
FastAPI
Pydantic
SQLite
Chroma 可后置
OpenAI-compatible LLM API
Qwen3-8B / Qwen3-14B
bge-m3
```

第一版建议：

```text
SQLite：事件日志、状态、nodes/edges
Chroma：长文本记忆和证据检索，后置
Qwen3-8B：抽取、叙事、NPC 对话
bge-m3：embedding，后置
```

---

## 4. 核心模块

### 4.1 EventLog

职责：

- 追加事件
- 查询事件
- 支持按回合 replay
- 作为世界状态真值源

原则：

> 所有世界变化必须写成事件。

事件示例：

```json
{
  "event_type": "TRANSFER_ITEM",
  "actor": "player",
  "targets": ["guard", "pass_token"],
  "state_deltas": [
    {
      "entity": "pass_token",
      "attr": "holder",
      "old": "player",
      "new": "guard"
    }
  ]
}
```

---

### 4.2 StateProjector

职责：

- 从事件日志投影当前状态
- 支持 replay_to_turn
- 更新 states 快照表

示例：

```text
初始状态
+ MOVE_ENTITY(player, village_gate)
+ TRANSFER_ITEM(pass_token, player -> guard)
= 当前状态
```

---

### 4.3 WorldGraph

职责：

- 维护节点和边
- 表达实体关系
- 支持 scope、valid_from、valid_to
- 支持按位置、关系、状态查询

节点类型：

```text
Character
Location
Item
Faction
Rule
Event
Quest
Ability
Resource
Memory
```

边类型：

```text
OWNS
LOCATED_AT
BELONGS_TO
TRUSTS
OPPOSES
DISCOVERED
TRIGGERS
REQUIRES
PRODUCES
CONSTRAINS
AFFECTS
PROMISED
```

---

### 4.4 RuleEngine

职责：

- 判定玩家行动是否合法
- 生成规范事件草案
- 阻止 LLM 直接改 canonical 状态

第一批规则：

```text
位置规则：玩家只能与当前位置附近实体交互
物品规则：只有持有物品才能使用/转交
门规则：门需要钥匙、权限或 NPC 放行
关系规则：NPC 信任达到阈值才解锁帮助
记忆规则：NPC 只能引用自己知道的事件
真值规则：rumor 不能直接变 canonical
```

---

### 4.5 AffordanceEngine

职责：

- 根据当前位置、附近实体、物品、关系、规则推导玩家当前可行动作

输出示例：

```json
[
  {
    "action_id": "talk_to_guard",
    "label": "和守卫交谈",
    "target_id": "guard",
    "risk": "low",
    "reason": "守卫位于当前地点"
  },
  {
    "action_id": "show_pass_token",
    "label": "向守卫出示通行令",
    "target_id": "guard",
    "risk": "low",
    "reason": "玩家持有通行令，守卫有检查权限"
  }
]
```

这是游戏感来源，不应完全交给 LLM 编造。

---

### 4.6 MemoryGraph

职责：

- 记录角色主观记忆
- 区分 canonical / player / npc / faction / rumor
- 支持 NPC 对话时回忆相关事件

关键原则：

> NPC 不是全知的。NPC 只能基于自己的记忆、误解、谣言和阵营认知行动。

---

### 4.7 Narrator

职责：

- 把规则结算结果写成叙事文本
- 生成 NPC 对话
- 不直接修改世界状态

输入是：

```text
玩家行动
规则判定结果
事件列表
当前状态
相关记忆
可行动作
```

输出是：

```text
叙事反馈
NPC 话语
下一步局势描述
```

---

## 5. 数据库设计

第一版 SQLite 表：

```sql
CREATE TABLE worlds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE turns (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    player_input TEXT,
    narration TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    turn_id TEXT,
    turn_index INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE state_deltas (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    attr TEXT NOT NULL,
    old_value_json TEXT,
    new_value_json TEXT,
    delta_json TEXT
);

CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    name TEXT,
    properties_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'canonical',
    valid_from_turn INTEGER NOT NULL,
    valid_to_turn INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_event_id TEXT
);

CREATE TABLE edges (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    src_id TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    properties_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'canonical',
    valid_from_turn INTEGER NOT NULL,
    valid_to_turn INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_event_id TEXT
);

CREATE TABLE states (
    world_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    attr TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_turn INTEGER NOT NULL,
    PRIMARY KEY (world_id, entity_id, attr)
);

CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    source_event_id TEXT,
    memory_text TEXT NOT NULL,
    truth_scope TEXT NOT NULL,
    salience REAL NOT NULL DEFAULT 0.5,
    valence REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 1.0,
    last_recalled_turn INTEGER
);
```

---

## 6. 第一批事件类型

```text
CREATE_ENTITY
MOVE_ENTITY
TRANSFER_ITEM
CHANGE_RELATION
SET_STATE
DELTA_RESOURCE
START_QUEST
COMPLETE_QUEST
FAIL_QUEST
ADD_MEMORY
ENABLE_RULE
DISABLE_RULE
```

---

## 7. 第一个 Demo：城门场景

不要一开始做复杂世界，先做一个极简城门 Demo。

### 地点

```text
村口
铁门
守卫室
内城
```

### 人物

```text
玩家
守卫阿洛斯
村长
```

### 物品

```text
通行令
银钥匙
钱袋
```

### 规则

```text
1. 铁门默认锁住。
2. 玩家可通过：通行令、钥匙、守卫放行、撬锁。
3. 守卫信任 >= 5 可放行。
4. 贿赂守卫会提高通过概率，但降低声望。
5. 偷钥匙失败会触发敌意。
6. 谣言不能直接当作事实。
```

这个场景能验证：

```text
位置
物品
关系
记忆
规则
可行动作
状态变化
事件回放
```

---

## 8. 最小 API

```text
POST /worlds
GET /worlds/{world_id}/state
GET /worlds/{world_id}/graph
GET /worlds/{world_id}/events
GET /worlds/{world_id}/affordances
POST /worlds/{world_id}/turn
POST /worlds/{world_id}/replay
```

### POST /turn 输入

```json
{
  "player_input": "我把通行令递给守卫，问他能不能放我进去"
}
```

### POST /turn 输出

```json
{
  "turn_index": 3,
  "narration": "守卫接过通行令，仔细看了看，神色缓和下来……",
  "events": [
    {
      "event_type": "TRANSFER_ITEM",
      "actor": "player",
      "targets": ["guard", "pass_token"]
    },
    {
      "event_type": "CHANGE_RELATION",
      "actor": "system",
      "targets": ["guard", "player"],
      "delta": {"trust": 2}
    }
  ],
  "affordances": [
    "进入铁门",
    "继续询问守卫",
    "查看守卫室"
  ]
}
```

---

## 9. 开发路线

### Phase 0：仓库初始化

目标：

```text
FastAPI 项目能跑
SQLite schema 能初始化
Demo world 能 seed
```

任务：

- 初始化 Python 项目
- 建 app 目录
- 写 schema.sql
- 写 seed_demo_world
- 写 README

### Phase 1：事件日志与状态投影

目标：

```text
事件是唯一真值源
状态可 replay
```

任务：

- EventLog.append()
- EventLog.list()
- Projector.apply_event()
- Projector.replay_to_turn()
- states 表更新

### Phase 2：WorldGraph

目标：事件能更新节点和边。

任务：

- add_node
- add_edge
- upsert_edge_version
- close_version
- query_neighbors
- query_by_scope

### Phase 3：Affordance

目标：系统能生成当前可行动作。

任务：

- action templates
- precondition validators
- location-based affordance
- item-based affordance
- npc-based affordance

### Phase 4：LLM 接入

目标：自然语言行动进入结构化流程。

任务：

- OpenAI-compatible client
- action_parser prompt
- narrator prompt
- extraction prompt
- JSON schema validation

### Phase 5：NPC Memory

目标：NPC 对话使用主观记忆。

任务：

- add_memory
- recall_memory
- salience / valence
- npc scope 查询
- memory-aware dialogue

---

## 10. 验收标准

必须通过：

```text
1. 事件日志能追加。
2. 当前状态能由事件投影得到。
3. 节点和边能随事件更新。
4. 可行动作能根据图谱和规则生成。
5. NPC 能引用自己的记忆。
6. rumor / npc / canonical 能分开。
7. 能 replay 到指定 turn。
8. LLM 不能绕过规则直接改状态。
```

测试用例：

```text
玩家没有钥匙 → 不能用钥匙开门
玩家拥有通行令 → 可以向守卫出示
守卫信任不足 → 不会主动放行
玩家贿赂守卫 → 信任上升但声望下降
玩家偷钥匙失败 → 守卫敌意上升
NPC 不知道的事 → 不能在对话里说出来
谣言存在 → NPC 可以听说，但 canonical 不改变
回滚到第 1 回合 → 钥匙归属恢复
```

---

## 11. 后续扩展方向

MVP 跑通后再扩展：

```text
WorldSpec：玩家输入世界想法后生成世界规格
Ontology 扩展：不同题材的类型扩展
World Tick：世界自运行
Quest Generator：从图谱矛盾生成任务
NPC Planner：根据目标、记忆和资源生成行动
Drama Graph：选择最有戏剧张力的前台事件
可视化：图谱、状态、事件时间线、NPC 记忆面板
```

---

## 12. 最终判断

第一阶段不要追求“多会讲故事”，而是验证：

> 事件日志 + 动态图谱 + 规则引擎 + 记忆作用域，是否能让 AI 游戏世界更稳定、更可玩。

只要最小闭环跑通，后续再做“玩家输入世界想法 → 生成初始世界 → AI 自运行世界”。
