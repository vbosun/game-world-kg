# Demo Completion Plan

本文记录 `full-local-demo-sqlite-kuzu-chroma-plan.md` 之后的剩余执行计划。

当前项目已经从城门 MVP 推进到可测试的三存储架构闭环，并已完成“可连续试玩 30-50 回合”的完整本地 Demo 验收。本计划保留为完成记录。

## Completion Status

已完成：

```text
Phase A: Village Movement Loop
Phase B: Village Action Effects
Phase C: Dynamic Tensions And Quests
Phase D: Three-Store Evaluation
Phase E: Debug UI Completion
Phase F: 30-50 Turn Playthrough
```

最终验证：

```text
67 tests passing
tests/test_demo_village_playthrough.py 覆盖 30+ turn 连续试玩
evaluation summary 纳入三存储一致性与 demo_village 指标
/debug 可查看 state/events/quests/tensions/explain/projectors
```

后续补充：

```text
NPC 对话记录采用双层结构：
1. NPC_DIALOGUE 事件保存完整问答、参与者和召回的 memory id，作为审计记录。
2. ADD_MEMORY 事件从本轮问答生成低 salience 的 NPC 主观记忆，source_event_id 指向 NPC_DIALOGUE。

这样原始对话可回放，长期记忆可检索，同时不会把对话内容直接污染 canonical。
```

## Current Status

已完成：

```text
SQLite EventLog / State / Outbox
KuzuStore + ChromaStore + Projectors
ActionTemplate / Predicate / Effect 基础
demo_village seed
TensionScanner
QuestGenerator from tensions
Chroma NPC memory recall
Explanation endpoints
58 tests passing
```

主要缺口（已关闭）：

```text
1. demo_village 玩法还不够连续
2. ActionTemplate 覆盖还不够完整
3. evaluation 指标还没覆盖三存储一致性
4. Debug UI 还没充分展示新增系统
```

## Phase A: Village Movement Loop

目标：`demo_village` 可以支撑连续试玩，玩家能到达主要地点。

任务：

```text
1. 增加通用移动模板 move_to_location
2. seed 地点连接关系
3. 支持玩家移动到至少 6 个地点
4. inner_city 继续受 iron_gate 限制
5. 扩展 ActionParser 规则关键词
6. AffordanceEngine 从模板列出可移动地点
```

初始可走路径：

```text
village_gate -> village_square
village_square -> tavern
village_square -> market_stall
village_square -> well
village_square -> warehouse
village_gate -> guard_room
iron_gate/open 后 -> inner_city
```

验收：

```text
demo_village 玩家可移动到至少 6 个地点
GET /worlds/demo_village/affordances 随地点变化
pytest 覆盖移动合法/非法路径
```

## Phase B: Village Action Effects

目标：村庄动作不只是 affordance 展示，而是能真实推进状态、记忆和任务。

优先动作：

```text
show_pass_token
request_access
ask_about_rumor
clarify_rumor
inspect_warehouse
request_warehouse_access
trade_grain
talk_to_mira
talk_to_borin
talk_to_chief
talk_to_warehouse_keeper
```

需要补充的 Effect：

```text
add_rumor
resolve_rumor
change_scope_memory
unlock_location
start_quest
complete_quest
```

最小闭环：

```text
ask_about_rumor -> player memory 指向 suspicious_traveler
clarify_rumor -> rumor resolved，不污染 canonical silver_key.holder
inspect_warehouse -> player 获得 ledger/grain 线索
request_warehouse_access -> 满足条件后 warehouse.locked=false
trade_grain -> 改变 grain_stock / merchant_borin gold / faction memory
```

验收：

```text
谣言线可发现 -> 澄清
仓库线可调查 -> 解锁 -> 交易
canonical 不被 rumor 污染
```

## Phase C: Dynamic Tensions And Quests

目标：任务从世界矛盾动态生成，并能随玩家行动消失或推进。

任务：

```text
1. gate open 后 locked_location 消失
2. rumor resolved 后 rumor_unresolved 消失
3. warehouse unlocked 后 quest_dependency_missing 消失
4. grain trade completed 后 resource_shortage 消失
5. QuestGenerator 过滤已完成任务
6. QuestValidator 严格校验 evidence、target entity、reward/failure effect
```

验收：

```text
至少 3 条 tension 初始可见
完成对应行动后 tension/quest 消失或推进
quest_traceability_rate >= 90%
```

## Phase D: Three-Store Evaluation

目标：最终验收指标纳入自动测试。

新增 evaluation 项：

```text
projector_rebuild_consistency
kuzu_graph_query_correct
chroma_memory_query_correct
chroma_scope_leak_rate
demo_village_movement_coverage
tension_resolution_rate
```

测试要求：

```text
写入事件后 SQLite states 更新
Kuzu graph 可查 neighbor/path
Chroma 可检索 memory/evidence
rebuild 后 Kuzu/Chroma 结果一致
NPC 不能读 player/private memory
rumor 不污染 canonical
Chroma recall 不直接改状态
```

验收：

```text
replay_accuracy = 100%
projector_rebuild_consistency = 100%
canonical_pollution_rate <= 5%
npc_privileged_knowledge_rate <= 10%
quest_traceability_rate >= 90%
```

## Phase E: Debug UI Completion

目标：开发者能在 `/debug` 看清世界为何变化。

补充面板：

```text
Tensions
Projection Status
Kuzu Graph
Chroma Evidence Search
Chroma Memory Search
Explain State
Explain Event
Explain Quest
Explain Memory
```

优先级：

```text
1. 展示 /tensions
2. 每个 quest 显示 tension_id
3. state 行支持 explain
4. memories 支持 explain
5. projector run/rebuild 结果更清晰
```

验收：

```text
打开 /debug 可以查看 state/events/quests/tensions/explain/projectors
不用 curl 也能完成主要调试
```

## Phase F: 30-50 Turn Playthrough

目标：固化完整 demo 试玩脚本。

测试脚本：

```text
通行线:
出示通行令 -> 请求放行 -> 进入内城

谣言线:
去酒馆 -> 问米拉 -> 找可疑旅人 -> 澄清谣言

仓库线:
去仓库 -> 检查门锁 -> 找村长 -> 请求仓库权限 -> 查账本 -> 协商粮食交易
```

实现：

```text
tests/test_demo_village_playthrough.py
```

验收：

```text
连续 30+ turn 不崩
关键 tension 会推进
NPC memory 可回忆
replay 后状态一致
```

## Recommended Order

后续开发顺序：

```text
1. Phase A: move_to_location + location connections
2. Phase B: 谣言线完整闭环
3. Phase B: 仓库线完整闭环
4. Phase C: tension/quest 动态消失和推进
5. Phase D: 三存储一致性 evaluation
6. Phase E: Debug UI 增强
7. Phase F: 30-50 回合 playthrough 测试
```

下一步建议立即做：

```text
Phase A: move_to_location + location connections + demo_village movement tests
```

原因：移动系统是 30-50 回合试玩的地基。没有移动，NPC、谣言、仓库线都会停留在“数据已 seed，但玩家到不了”的状态。
