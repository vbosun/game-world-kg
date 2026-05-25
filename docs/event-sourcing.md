# Event Sourcing 与一致性设计

## 1. 核心原则

Game World KG 的真值源不是图数据库，也不是向量库，而是**事务型事件日志**。

```text
Event Log = Source of Truth
WorldGraph = Materialized View
Vector Memory = Evidence Retrieval Layer
State Store = Projected Snapshot
```

所有世界变化必须先写入事件日志，再由投影器更新状态、图谱和记忆索引。

---

## 2. 为什么事件日志是核心

如果直接维护当前状态：

```text
玩家位置 = 村口
守卫信任 = 5
钥匙持有者 = 玩家
```

系统很难回答：

- 为什么守卫信任是 5？
- 第 3 回合时钥匙在哪里？
- NPC 是什么时候知道这件事的？
- 某个状态能否回滚？
- LLM 是否偷偷改过状态？

事件日志解决这些问题：

```text
evt_001: 玩家获得通行令
evt_002: 玩家向守卫出示通行令
evt_003: 守卫信任 +2
evt_004: 守卫打开铁门
```

当前状态由事件 replay 得到。

---

## 3. EventRecord 标准结构

```json
{
  "event_id": "evt_00042",
  "world_id": "demo_world",
  "turn_id": "turn_12",
  "turn_index": 12,
  "event_type": "TRANSFER_ITEM",
  "actor_id": "player",
  "participants": ["player", "guard_alos", "pass_token"],
  "causal_parents": ["evt_00038"],
  "payload": {
    "item_id": "pass_token",
    "from": "player",
    "to": "guard_alos"
  },
  "state_deltas": [
    {
      "entity_id": "pass_token",
      "attr": "holder",
      "old_value": "player",
      "new_value": "guard_alos"
    }
  ],
  "evidence_refs": [
    {
      "source_id": "turn_12_input",
      "span": [0, 12],
      "extractor": "action_parser_v1",
      "confidence": 0.95
    }
  ],
  "created_at": "2026-05-25T00:00:00Z"
}
```

要求：

- event 追加式不可变。
- 修正历史用新事件，不修改旧事件。
- state_deltas 必须能被 replay。
- evidence_refs 必须绑定来源。

---

## 4. StateDelta 设计

StateDelta 表示事件带来的状态变化。

```json
{
  "entity_id": "guard_alos",
  "attr": "trust.player",
  "old_value": 3,
  "new_value": 5,
  "delta": 2,
  "scope": "canonical"
}
```

类型：

```text
SET_STATE：设置属性
DELTA_RESOURCE：资源增减
MOVE_ENTITY：位置迁移
TRANSFER_ITEM：持有者变化
CHANGE_RELATION：关系值变化
ENABLE_RULE：启用规则
DISABLE_RULE：禁用规则
ADD_MEMORY：增加记忆
```

---

## 5. 事件类型

第一批事件类型：

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
CORRECTION_EVENT
REVERT_EVENT
```

### 5.1 CREATE_ENTITY

创建实体。

```json
{
  "event_type": "CREATE_ENTITY",
  "payload": {
    "stable_key": "guard_alos",
    "entity_type": "Character",
    "name": "守卫阿洛斯"
  }
}
```

### 5.2 MOVE_ENTITY

迁移位置。

```json
{
  "event_type": "MOVE_ENTITY",
  "payload": {
    "entity_id": "player",
    "from": "village_square",
    "to": "village_gate"
  }
}
```

### 5.3 TRANSFER_ITEM

转移物品。

```json
{
  "event_type": "TRANSFER_ITEM",
  "payload": {
    "item_id": "pass_token",
    "from": "player",
    "to": "guard_alos"
  }
}
```

### 5.4 CHANGE_RELATION

改变关系。

```json
{
  "event_type": "CHANGE_RELATION",
  "payload": {
    "src": "guard_alos",
    "rel": "TRUSTS",
    "dst": "player",
    "attr": "value",
    "delta": 2
  }
}
```

### 5.5 ADD_MEMORY

加入主观记忆。

```json
{
  "event_type": "ADD_MEMORY",
  "payload": {
    "owner_id": "guard_alos",
    "memory_text": "玩家曾主动出示合法通行令。",
    "source_event_id": "evt_00042",
    "truth_scope": "npc",
    "salience": 0.7,
    "valence": 0.2
  }
}
```

---

## 6. Replay 机制

### 6.1 基本流程

```text
读取初始世界种子
读取 turn <= N 的全部事件
按 turn_index + event_order 排序
逐条 apply_event
得到 turn N 的状态
```

伪代码：

```python
def replay(world_id: str, to_turn: int | None = None) -> WorldProjection:
    state = load_initial_state(world_id)
    events = event_log.list(world_id, to_turn=to_turn)
    for event in events:
        state = projector.apply_event(state, event)
    return state
```

### 6.2 Replay 必须保证确定性

同一批事件 replay 后必须得到同一状态。

要求：

- RuleEngine 的随机结果必须写入事件。
- LLM 生成结果不能在 replay 时重新调用。
- 时间、随机数、外部输入都要进入事件 payload。

错误示例：

```text
replay 时重新让 LLM 判断 NPC 反应
```

正确做法：

```text
第一次生成 NPC 反应时写成事件，replay 只读取事件结果
```

---

## 7. Rollback 机制

### 7.1 本地 MVP

最简单方案：

```text
删除指定 turn 之后的状态快照
replay 到目标 turn
重新物化 WorldGraph / states
```

### 7.2 生产模式

不建议物理删除事件。

使用：

```text
REVERT_EVENT
CORRECTION_EVENT
BRANCH_WORLD
```

示例：

```json
{
  "event_type": "REVERT_EVENT",
  "payload": {
    "target_event_id": "evt_00042",
    "reason": "玩家撤销行动分支"
  }
}
```

---

## 8. Graph Materialization

事件日志写入后，WorldGraph 作为物化视图更新。

```text
Event Log
  ↓
Projector
  ↓
States
  ↓
WorldGraph nodes/edges
  ↓
Memory / Vector indexes
```

图谱可以重建，所以不能作为唯一真值源。

如果图谱损坏：

```text
清空物化图
从事件日志 replay 重建
```

---

## 9. 本地 MVP 一致性

本地 MVP 使用 SQLite 单机事务即可。

一个 turn 的提交流程：

```text
BEGIN TRANSACTION
1. 写 turn
2. 写 events
3. 写 state_deltas
4. 更新 states
5. 更新 nodes/edges
6. 写 memories
COMMIT
```

如果中间失败，整个 turn 回滚。

---

## 10. 生产模式：Outbox

当系统扩展到 Postgres + Neo4j + Qdrant 时，不要尝试跨存储强事务。

推荐使用 outbox：

```text
Postgres EventLog 提交成功
  ↓
outbox 写入 graph_update / vector_update
  ↓
异步 worker 幂等消费
  ↓
Neo4j / Qdrant 更新物化视图
```

原则：

```text
只要 event_log 提交成功，世界真值就成立。
图和向量索引可以延迟一致。
```

### Outbox 表

```sql
CREATE TABLE outbox (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    processed_at TEXT
);
```

### 幂等要求

消费者必须支持重复消费。

幂等键：

```text
event_id + projection_type
```

---

## 11. 读路径策略

### 11.1 强一致读

用于规则判定。

```text
读取 EventLog / States
```

### 11.2 结构查询读

用于叙事、NPC 对话、任务生成。

```text
读取 WorldGraph
```

### 11.3 长文本检索读

用于证据、历史剧情、语义记忆。

```text
读取 Vector Memory
```

### 11.4 读旧图问题

生产异步物化后，WorldGraph 可能落后 EventLog。

解决：

- 查询返回 `projection_turn`。
- 如果低于当前 turn，读路径可选择等待、fallback 到 states，或接受弱一致。

---

## 12. 审计与解释

任何状态都应能解释来源。

查询：

```text
为什么 guard_alos 信任 player 是 5？
```

返回：

```text
evt_00021: 玩家帮助守卫找回钱袋，trust +2
evt_00042: 玩家出示合法通行令，trust +2
evt_00057: 玩家贿赂失败，trust -1
当前 trust = 5
```

这对调试和玩家体验都重要。

---

## 13. 测试要求

### 13.1 Replay 测试

```text
给定 1000 条事件
replay 到最新 turn
当前 states 必须一致
```

### 13.2 Rollback 测试

```text
replay 到 turn 10
状态必须等于当时快照
```

### 13.3 幂等测试

```text
同一个 graph_update 消费两次
nodes/edges 不应重复或污染
```

### 13.4 LLM 隔离测试

```text
replay 过程中不得调用 LLM
```

### 13.5 Scope 测试

```text
rumor 不能直接修改 canonical
npc memory 不能直接变成 world truth
```

---

## 14. MVP 简化方案

第一版直接用 SQLite：

```text
events
state_deltas
states
nodes
edges
memories
```

暂时不做：

```text
outbox
异步物化
跨库一致性
多世界分支
```

但文档和数据结构要预留这些演进方向。
