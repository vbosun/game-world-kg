# Game World KG MVP

事件溯源驱动的动态游戏世界知识图谱内核。

## 目标

验证 AI 生成式游戏世界能否通过 **Event Log + WorldGraph + Rule Engine + Memory Scope + LLM** 实现：

- 状态一致
- NPC 不失忆
- 行动可验证
- 可行动作由世界状态推导
- 世界状态可回放、回滚、审计
- 任务可从世界矛盾中自然生长

## 核心原则

1. **Event Log 是真值源**  
   所有世界变化必须写成事件，当前状态由事件投影得到。

2. **WorldGraph 是结构化世界视图**  
   图谱用于表达人物、地点、物品、规则、事件、关系和当前状态。

3. **Affordance 决定玩家可行动作**  
   游戏感来自“当前能做什么”，而不是纯文本剧情。

4. **Rule Engine 是合法性裁判**  
   LLM 不能绕过规则直接改 canonical 状态。

5. **LLM 只负责叙事和候选抽取**  
   LLM 负责解析、叙事、对话、补全，但不能直接修改世界真值。

6. **Memory Scope 区分世界真相和主观记忆**  
   canonical / player / npc / faction / rumor 必须分开。

7. **所有状态变化必须可回放**  
   支持 replay、rollback、debug 和因果解释。

## 文档

基础文档：

- [游戏通用知识图谱研究报告](docs/research-report.md)
- [本地 MVP 落地方案](docs/mvp-plan.md)
- [SQLite + Kuzu + Chroma 完整本地 Demo 方案](docs/full-local-demo-sqlite-kuzu-chroma-plan.md)

严格对齐研究报告的详细设计：

- [本体与版本化设计](docs/ontology.md)
- [Event Sourcing 与一致性设计](docs/event-sourcing.md)
- [混合抽取与图谱更新管线](docs/extraction-pipeline.md)
- [评估体系与 PoC 计划](docs/evaluation.md)
- [完整本地 Demo 剩余完成计划](docs/demo-completion-plan.md)

## 当前阶段

第一阶段不是做完整游戏，而是验证最小闭环：

```text
玩家行动
→ 结构化 action
→ 规则判定
→ 事件追加
→ 状态投影
→ 图谱更新
→ 记忆更新
→ affordance 变化
→ LLM 叙事
```

下一阶段主线是 **SQLite + Kuzu + Chroma 完整本地 Demo**：严格按照研究报告，把当前城门 MVP 升级为三存储本地架构：

```text
SQLite  = 事务型事件日志 / source of truth / 状态投影 / 审计
Kuzu    = 本地嵌入式属性图 / 世界结构图 / 时态关系查询
Chroma  = 本地向量记忆 / 长文本证据 / 叙事与 NPC 记忆检索
```

目标是做出一个可本地运行、可试玩 30～50 回合的小型村庄 Demo，完整验证事件日志、属性图、规则引擎、Affordance、NPC 记忆、谣言、任务生成、证据检索和 replay/rollback。

## 推荐第一个 Demo

先做一个小村庄本地 Demo：

```text
地点：村口、铁门、守卫室、村广场、酒馆、仓库、井边、内城入口、市集摊位
人物：玩家、守卫、酒馆老板、商人、村长、可疑旅人、仓库管理员
物品：通行令、银钥匙、仓库钥匙、钱袋、粮袋、传闻纸条、水桶、仓库账本
核心线：通行线、谣言线、仓库线
```

这个 Demo 用于验证：

```text
canonical / npc / faction / rumor 分层
SQLite EventLog 真值源
Kuzu 世界属性图查询
Chroma 长文本证据和记忆检索
ActionTemplate + RuleEngine + Affordance
TensionScanner + QuestGenerator
ExplanationService
```

## 本地运行

安装依赖：

```bash
uv sync --extra test
```

启动 API：

```bash
uv run python -m game_world_kg
```

默认会初始化 `game_world_kg.sqlite3` 并 seed 城门 Demo，世界 ID 为 `demo_gate`。

调试面板：

```text
http://127.0.0.1:8000/debug
```

AI 使用 OpenAI-compatible 接口，默认本地地址：

```text
GAME_WORLD_KG_LLM_BASE_URL=http://localhost:5001/v1
GAME_WORLD_KG_LLM_MODEL=qwen3
GAME_WORLD_KG_LLM_API_KEY=
GAME_WORLD_KG_LLM_TIMEOUT=30
GAME_WORLD_KG_LLM_ENABLED=1
```

也可以复制 `.env.example` 为 `.env`，在 `.env` 中配置本地模型地址和 API key。系统环境变量优先级高于 `.env`。

LLM 只生成候选 action 和叙事文本；canonical 状态仍只能由 Rule Engine 写入。

最小接口：

```text
POST /worlds
GET /worlds/demo_gate/state
GET /worlds/demo_gate/graph
GET /worlds/demo_gate/events
GET /worlds/demo_gate/affordances
GET /worlds/demo_gate/quests
GET /worlds/demo_gate/memories
GET /worlds/demo_gate/memories/guard_alos/recall?query=通行令
GET /worlds/demo_gate/neighbors/guard_alos
POST /worlds/demo_gate/turn
POST /worlds/demo_gate/npc/guard_alos/dialogue
POST /worlds/demo_gate/replay
```

提交一回合：

```bash
curl -X POST http://127.0.0.1:8000/worlds/demo_gate/turn \
  -H "Content-Type: application/json" \
  -d '{"player_input":"我把通行令递给守卫，问他能不能放我进去"}'
```

询问 NPC 记忆：

```bash
curl -X POST http://127.0.0.1:8000/worlds/demo_gate/npc/guard_alos/dialogue \
  -H "Content-Type: application/json" \
  -d '{"question":"你记得我做过什么吗"}'
```

运行回归测试：

```bash
uv run pytest
```

运行 MVP 评估：

```bash
uv run python -m game_world_kg.evaluation
```

评估输出覆盖：

```text
PoC 1：文本日志建图、证据覆盖、scope 分流
LLM 抽取：高歧义文本候选、scope 安全、canonical 防污染
PoC 2：事件回放与 LLM 隔离
PoC 3：Affordance 合法性
PoC 4：NPC 记忆与 scope 安全
PoC 5：任务链生成、依赖合法性、证据追溯
```
