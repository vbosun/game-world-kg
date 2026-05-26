# 小型本地 Demo 下一步方案

## 1. 背景判断

当前仓库已经完成了 Game World KG MVP 的第一版验证：

```text
玩家输入
→ action 解析
→ RuleEngine 判定
→ EventLog 写入
→ StateProjector 投影
→ WorldGraph 查询
→ Affordance 生成
→ Memory scope 分层
→ Quest 候选
→ LLM 叙事
→ evaluation PoC
```

这说明项目已经不再是纯方案，而是具备了可运行内核。

但当前实现仍然是**城门 Demo 的硬编码验证版**，核心规则、affordance、quest 多数围绕固定实体展开：

```text
guard_alos
pass_token
silver_key
iron_gate
village_gate
inner_city
```

因此下一步不应该继续堆更多剧情，也不应该立刻做“大世界生成”。

下一步目标应定义为：

> 在当前 MVP 基础上，实现一个小型本地可试玩 Demo，并把城门场景里的硬编码逻辑抽象成可复用的 Game World KG 内核。

---

## 2. 研究报告对下一步的约束

研究报告给出的方向是：

```text
事件溯源属性图
+
规则引擎
+
向量记忆
```

并明确要求游戏 KG 不是静态设定库，而是：

```text
时间感知
事件驱动
规则可验证
记忆可分层
动作可执行
可回放审计
```

因此本地 Demo 的下一步必须遵守以下原则：

1. **EventLog 仍然是 source of truth**  
   所有世界变化必须先成为事件，不允许 LLM 直接改 canonical 状态。

2. **WorldGraph 是物化视图**  
   图谱用于查询人物、地点、物品、规则、记忆和关系，但可以由事件日志重建。

3. **Affordance 是游戏感核心**  
   当前可行动作必须来自规则与状态推导，而不是纯 LLM 编造。

4. **Memory scope 不能混淆**  
   canonical / npc / faction / rumor / player 必须分层。

5. **任务必须从图谱矛盾中生长**  
   不做随机任务，不做纯 LLM 任务，而是从 tension 生成任务候选。

6. **评估不能只看文本好不好看**  
   要继续评估 replay、scope 安全、action 合法性、quest 可追溯性和 NPC 越权知识率。

---

## 3. 下一阶段名称

建议命名：

```text
Beta 0：Local Playable Demo
```

目标：

> 把当前城门 MVP 扩展为一个 20～50 回合可试玩的小型本地 Demo，同时把 action/rule/affordance/quest 从硬编码函数升级为数据驱动模板。

---

## 4. Demo 范围

### 4.1 地图范围

不要做大世界，只做一个小村庄局部。

```text
village_gate      村口
iron_gate         铁门
guard_room        守卫室
village_square    村广场
tavern            酒馆
warehouse         仓库
well              井边
inner_city        内城入口
```

这些地点足够验证：

```text
移动
门禁
交易
传闻
物品转移
NPC 记忆
任务生成
状态回放
```

### 4.2 NPC 范围

```text
player               玩家
guard_alos           守卫阿洛斯
tavern_keeper_mira   酒馆老板米拉
merchant_borin       商人伯林
village_chief        村长
suspicious_traveler  可疑旅人
```

每个 NPC 至少有：

```text
location
faction / role
trust.player
hostility.player
known_memories
basic_goal
```

### 4.3 物品范围

```text
pass_token        通行令
silver_key        银钥匙
coin_pouch        钱袋
warehouse_key     仓库钥匙
grain_bag         粮袋
rumor_note        传闻纸条
water_bucket      水桶
```

### 4.4 核心玩法线

保留城门线，并扩展成三条小型事件线：

```text
1. 通行线
通过通行令、信任、钥匙、贿赂或其他方式进入内城。

2. 传闻线
玩家被传闻牵连到钥匙失窃，需澄清、调查或利用传闻。

3. 仓库线
村庄仓库缺粮或钥匙失踪，引出商人、村长、守卫之间的矛盾。
```

这三条线足够验证：

```text
canonical 真值
npc 主观记忆
rumor 谣言
faction 认知
quest 从 tension 生成
```

---

## 5. 技术目标

### 5.1 从硬编码 Affordance 到 ActionTemplate

当前 `AffordanceEngine` 直接判断固定实体。下一步改成模板驱动。

新增概念：

```text
ActionTemplate
Precondition
EffectTemplate
TargetSelector
RiskPolicy
```

示例：

```json
{
  "action_id": "show_item_to_npc",
  "label_template": "向{target}出示{item}",
  "target_selector": {
    "entity_type": "Character",
    "same_location": true
  },
  "args": {
    "item": {
      "must_be_held_by": "player"
    }
  },
  "preconditions": [
    {"type": "same_location", "a": "player", "b": "$target"},
    {"type": "has_item", "actor": "player", "item": "$item"}
  ],
  "effects": [
    {"type": "reveal_item", "actor": "player", "target": "$target", "item": "$item"}
  ],
  "risk": "low"
}
```

第一版可以先用 JSON seed，不需要复杂 DSL。

---

### 5.2 RuleEngine 拆成 Predicate + Effect Executor

当前 RuleEngine 使用 action_id 分支函数。

下一步拆成：

```text
PredicateEvaluator
EffectExecutor
ActionResolver
RuleResult
```

第一批 Predicate：

```text
same_location(a, b)
has_item(actor, item)
state_equals(entity, attr, value)
relation_at_least(entity, attr, value)
resource_at_least(entity, attr, value)
scope_allowed(scope)
memory_exists(owner, topic, scope)
```

第一批 Effect：

```text
transfer_item
set_state
delta_resource
change_relation
add_memory
move_entity
start_quest
complete_quest
```

目标：

> 新增一个世界行为时，不再写新的 Python 分支，而是新增 action template + rule template。

---

### 5.3 加 TensionScanner

新增模块：

```text
src/game_world_kg/tension.py
```

职责：扫描 WorldGraph / State / Memory，找出可生成任务的矛盾。

第一批 tension 类型：

```text
locked_location
trust_below_threshold
rumor_unresolved
item_missing
resource_shortage
npc_goal_blocked
hostility_rising
quest_dependency_missing
```

输出示例：

```json
{
  "tension_id": "tension_guard_trust_low",
  "type": "trust_below_threshold",
  "reason": "守卫信任不足，无法主动放行。",
  "affected_entities": ["guard_alos", "player", "iron_gate"],
  "evidence": [
    {"source_type": "state", "entity_id": "guard_alos", "attr": "trust.player", "value": 3}
  ],
  "suggested_actions": ["show_pass_token", "bribe_guard"]
}
```

QuestGenerator 下一步应该从 tension 生成任务，而不是自己写固定 if。

---

### 5.4 补 State Explanation

新增接口：

```text
GET /worlds/{world_id}/explain/state/{entity_id}/{attr}
```

示例：

```text
为什么 guard_alos.trust.player = 5？
```

返回：

```json
{
  "entity_id": "guard_alos",
  "attr": "trust.player",
  "current_value": 5,
  "sources": [
    {
      "event_id": "evt_001",
      "event_type": "CHANGE_RELATION",
      "delta": 2,
      "reason": "玩家出示通行令"
    }
  ]
}
```

这对应研究报告里的：

```text
可解释性
evidence_refs
event replay
query trace
```

---

### 5.5 Evidence Store 先用 SQLite，不急着接 Chroma

研究报告推荐本地 Demo 可使用：

```text
SQLite + Kuzu + Chroma
```

但当前下一步不要马上引入 Kuzu/Chroma。建议先补：

```text
source_texts
evidence_refs
extraction_candidates
```

先把证据链跑稳。

Beta 1 再接：

```text
Chroma + bge-m3
```

原因：

> 当前瓶颈不是语义检索性能，而是 evidence trace、scope 分流和 action/rule 模板化。

---

## 6. 建议新增 / 修改的数据表

### 6.1 action_templates

```sql
CREATE TABLE IF NOT EXISTS action_templates (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    label_template TEXT NOT NULL,
    target_selector_json TEXT NOT NULL DEFAULT '{}',
    arg_schema_json TEXT NOT NULL DEFAULT '{}',
    preconditions_json TEXT NOT NULL DEFAULT '[]',
    effects_json TEXT NOT NULL DEFAULT '[]',
    risk TEXT NOT NULL DEFAULT 'low',
    enabled INTEGER NOT NULL DEFAULT 1,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
```

### 6.2 source_texts

```sql
CREATE TABLE IF NOT EXISTS source_texts (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    text TEXT NOT NULL,
    turn_id TEXT,
    created_at TEXT NOT NULL
);
```

### 6.3 evidence_refs

```sql
CREATE TABLE IF NOT EXISTS evidence_refs (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    span_start INTEGER,
    span_end INTEGER,
    text TEXT,
    extractor TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL
);
```

### 6.4 extraction_candidates

```sql
CREATE TABLE IF NOT EXISTS extraction_candidates (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    candidate_json TEXT NOT NULL,
    scope TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'candidate',
    reason TEXT,
    created_at TEXT NOT NULL
);
```

### 6.5 tensions

可以先不落表，运行时计算；若需要调试，可加入：

```sql
CREATE TABLE IF NOT EXISTS tensions (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    tension_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    created_turn INTEGER NOT NULL,
    resolved_turn INTEGER
);
```

---

## 7. 小型本地 Demo 体验目标

Demo 完成后，玩家应该能这样玩：

```text
你站在村口，铁门紧闭。守卫阿洛斯在一旁巡逻，酒馆方向传来低声议论。

可行动作：
1. 向守卫出示通行令
2. 和守卫交谈
3. 去酒馆打听传闻
4. 查看铁门
5. 尝试偷取银钥匙
```

玩家去酒馆后：

```text
酒馆老板米拉告诉你，村里有人说昨夜守卫室附近出现过陌生人。
```

系统应写入：

```text
Memory(scope=rumor, owner=village/tavern_keeper)
不修改 canonical: silver_key.holder
```

玩家向守卫解释或出示证据后：

```text
谣言 tension 被标记为 resolved
守卫 trust.player 上升
相关 quest 完成或更新
```

这个 Demo 要体现：

```text
同一件事在 canonical / npc / rumor 中可有不同状态
NPC 不全知
任务从 tension 来
玩家行动可被解释
状态可回放
```

---

## 8. 验收标准

### 8.1 功能验收

必须实现：

```text
1. 小村庄 6～8 个地点可移动
2. 至少 5 个 NPC
3. 至少 3 条 tension 线
4. 至少 5 个 action template
5. 至少 5 个 predicate
6. 至少 5 个 effect executor
7. QuestGenerator 从 TensionScanner 获取候选
8. State explanation endpoint 可解释至少 3 类状态
9. source_texts / evidence_refs / candidates 可保存证据链
10. 回放到任意 turn 后状态一致
```

### 8.2 评估验收

```text
replay 正确率 = 100%
非法动作拦截率 >= 95%
canonical 污染率 <= 5%
NPC 越权知识率 <= 10%
quest traceability >= 90%
affordance 相关率 >= 85%
```

### 8.3 体验验收

本地连续试玩 30 回合，应满足：

```text
NPC 能记住玩家至少 3 件互动
至少 1 条 rumor 可以被传播/澄清
至少 1 个任务来自 tension，而非固定剧本
至少 1 次状态解释能说明“为什么现在是这样”
玩家当前可行动作随状态明显变化
```

---

## 9. 建议开发顺序

### Phase A：证据链与解释能力

优先级最高，因为它最符合研究报告，也能保护后续扩展。

任务：

```text
A1. 新增 source_texts / evidence_refs / extraction_candidates 表
A2. 所有 ExtractionPipeline 输入先保存 source_text
A3. EventLog 写入时同步保存 evidence_refs
A4. 新增 state explanation endpoint
A5. 增加 pytest：状态解释必须能追溯 event
```

### Phase B：ActionTemplate + Affordance 通用化

任务：

```text
B1. 新增 action_templates 表和 seed
B2. 实现 PredicateEvaluator
B3. 实现 EffectExecutor
B4. AffordanceEngine 改为扫描 action_templates
B5. 保留旧硬编码逻辑作为 fallback，逐步迁移
```

### Phase C：RuleEngine 模板化

任务：

```text
C1. ActionResolver 根据 action_id 找模板
C2. RuleEngine 执行模板 preconditions
C3. 通过 effects 生成 EventRecord / StateDelta
C4. 迁移 show_pass_token / ask_guard_open_gate / bribe_guard
C5. 增加模板化规则回归测试
```

### Phase D：TensionScanner + Quest 重构

任务：

```text
D1. 新增 TensionScanner
D2. 实现 trust_below_threshold / locked_location / rumor_unresolved
D3. QuestGenerator 改为从 tensions 生成任务
D4. QuestValidator 校验 tension evidence
D5. 增加 quest traceability 测试
```

### Phase E：小村庄 Demo 扩展

任务：

```text
E1. seed 新地点
E2. seed 新 NPC
E3. seed 新物品
E4. seed 新 action templates
E5. debug 面板显示地点、NPC、tensions、quests
E6. README 增加本地试玩路径
```

---

## 10. 给 Codex 的推荐 Issue 列表

### Issue 1

```text
Add evidence store and state explanation endpoint
```

验收：

```text
- source_texts/evidence_refs/extraction_candidates 表存在
- /explain/state/{entity}/{attr} 能返回相关事件
- pytest 覆盖 trust.player 和 pass_token.holder
```

### Issue 2

```text
Introduce action_templates and template-based affordance generation
```

验收：

```text
- action_templates 表存在
- seed 至少 5 个 action templates
- AffordanceEngine 能基于模板生成 show_pass_token / bribe_guard
- 旧测试通过
```

### Issue 3

```text
Refactor RuleEngine into predicate/effect executor
```

验收：

```text
- same_location / has_item / relation_at_least / state_equals 可用
- transfer_item / change_relation / add_memory / set_state 可用
- show_pass_token 通过模板执行
```

### Issue 4

```text
Add TensionScanner and refactor quest generation
```

验收：

```text
- locked_location / trust_below_threshold / rumor_unresolved 可被扫描
- QuestGenerator 不再直接硬编码所有任务
- quest evidence 可追溯 tension
```

### Issue 5

```text
Expand demo world into small village playable loop
```

验收：

```text
- 至少 6 个地点
- 至少 5 个 NPC
- 至少 3 条 tension
- 连续 30 回合不破坏 replay / scope / affordance 测试
```

---

## 11. 不建议现在做的事

暂时不要做：

```text
1. 玩家输入一句话自动生成任意世界
2. 大地图
3. 战斗系统
4. Neo4j / Qdrant / Kuzu 替换
5. Chroma + embedding 大规模记忆检索
6. 复杂前端
7. 多租户 / 云部署
```

这些都应该放到 Beta 1 或 Beta 2。

当前最重要的是：

> 把可运行 MVP 抽象成可复用内核，并做出一个小而密的本地可试玩 Demo。

---

## 12. 阶段完成后的状态

Beta 0 完成后，项目应达到：

```text
一个小村庄 Demo 可以本地试玩 30～50 回合；
世界状态能从事件日志回放；
NPC 记忆和谣言不污染 canonical；
当前可行动作由 action template + rule predicate 推导；
任务从 tension 生成；
关键状态可解释来源；
评估脚本和 pytest 能防止核心机制退化。
```

这时再进入下一阶段：

```text
Beta 1：WorldSpec 小世界生成器
```

也就是：

```text
玩家输入世界想法
→ 生成起点区域
→ 生成 NPC / 物品 / 规则 / action templates / tensions
→ 使用同一套本地内核运行
```

只有 Beta 0 完成后，Beta 1 才不会变成“LLM 每次重新脑补一个世界”。
