# Beta 3：Playable Game Layer 游戏开发方案

## 1. 方案定位

本方案用于把当前 `game-world-kg` 项目从：

```text
Game World KG 内核
+ SQLite/Kuzu/Chroma 三存储本地 Demo
+ WorldSpec 小世界生成器
+ NPC Memory Graph
```

推进到真正可玩的游戏形态：

```text
AI 生成小世界文字沙盒 RPG
```

Beta 3 的核心目标不是继续证明“世界能生成”，而是证明：

> 玩家能在生成出来的小世界里持续游玩，形成目标、路线、关系、身份和自己的故事。

项目必须继续严格遵守既有研究报告与代码架构原则：

```text
1. SQLite EventLog 是 source of truth。
2. Kuzu 是世界属性图 / 关系查询层。
3. Chroma 是长期记忆 / 证据检索层。
4. RuleEngine / ActionTemplate 决定合法行动。
5. LLM 只生成候选、叙事和解释，不直接改 canonical。
6. canonical / player / npc / faction / rumor 必须隔离。
7. NPC 自运行必须写事件，不能直接改状态。
8. Quest 必须从 Tension 生成，并能追溯 evidence。
9. 所有关键状态变化必须可 replay / explain。
```

一句话定位：

> Beta 3 要把“世界模拟器”包装成“玩家有目标、有成长、有反馈、有失败、有任务日志、有 UI 的文字沙盒 RPG”。

---

## 2. 从研究报告得到的设计原则

根据 AI 小世界 RPG 可玩性研究报告，本项目最重要的设计纲领是：

```text
游戏应该是一台“身份与局势生成器”，不是一台“文字续写器”。
```

也就是说，玩家不是来听 AI 讲一段无限文本，而是要在一个可运行的小社会里：

```text
低起点进入
→ 认识人物
→ 学会规则
→ 获得线索
→ 改变关系
→ 获得权限
→ 形成路线
→ 被世界记住
→ 变成某种人
```

因此，Beta 3 的核心不应是“更长的叙事”，而应是：

```text
每回合都产生结构化世界变化。
```

每次玩家行动后，系统都应该尽量产生以下一种或多种变化：

```text
资源变化
关系变化
知识变化
权限变化
身份变化
任务变化
传闻变化
地点状态变化
NPC 记忆变化
势力态度变化
```

如果一回合只有漂亮文案，没有结构变化，那就是失败回合。

---

## 3. 最小可玩核心循环

Beta 3 的最小可玩循环固定为：

```text
看见局面
→ 选择一个局部目标
→ 用合法行动撬动世界
→ 获得分层反馈
→ 看到 NPC / 势力 / 任务 / 传闻变化
→ 新机会、新压力、新权限出现
```

工程上对应：

```text
Render Scene
→ List Affordances
→ Player Action / Free Input
→ Intent Parser
→ ActionTemplate Binder
→ RuleEngine Validate
→ Append EventLog
→ Project State / Kuzu / Chroma
→ Foreground NPC Tick
→ Rumor / Witness Propagation
→ Tension / Quest Update
→ Drama Foreground Selection
→ Render Feedback
```

这个循环必须优先于所有“剧情描写”。

---

## 4. Beta 3 的产品形态

第一版不使用传统游戏引擎，不上 Unity / Unreal / Godot。

推荐形态：

```text
FastAPI 后端
+ Web 前端
+ 文字 RPG UI
+ 状态 / 任务 / 关系 / 日志面板
```

理由：

```text
1. 当前项目核心玩法是信息、选择、状态变化和社会关系，不是物理、动画或 3D 空间。
2. Web UI 最适合展示 EventLog、任务、关系、传闻、因果链和 explain。
3. 过早使用游戏引擎会把开发重心带到地图、动画、资源管理，而不是核心可玩循环。
```

建议 UI 布局：

```text
左侧：场景 / 地点 / 可见 NPC / 地图关系
中间：叙事输出 / 对话记录 / 行动反馈
右侧：角色状态 / 任务 / 关系 / 传闻 / 权限
底部：推荐行动按钮 + 自由输入框
可展开：事件时间线 / explain 因果链 / debug view
```

后续如果 Web 版证明好玩，再考虑 Godot 作为表现层，核心世界逻辑仍留在后端。

---

## 5. Beta 3 必须新增的核心系统

## 5.1 Playable Turn Kernel

### 目标

把当前 API/Debug 形态变成真正游戏回合。

### 每回合流程

```text
1. 读取当前 world/player state。
2. 用 Kuzu 查询当前位置、附近 NPC、地点连接、active tensions。
3. 用 Chroma 召回玩家可知线索、当前 NPC 相关记忆。
4. AffordanceEngine 生成 3～7 个推荐行动。
5. UI 渲染场景、行动、任务、关系、状态。
6. 玩家点击按钮或自由输入。
7. 自由输入必须绑定到当前合法 ActionTemplate。
8. RuleEngine 校验。
9. 写 EventLog。
10. StateProjector / KuzuProjector / ChromaProjector 更新。
11. Foreground NPC Scheduler 推进 1～3 个相关 NPC。
12. Rumor/Witness 传播。
13. TensionScanner / QuestGenerator 更新。
14. Drama Manager v0 选择一个新前台机会。
15. Narrator 输出短反馈 + 结构化变化摘要。
```

### 关键要求

```text
自由输入不能直接改变世界。
无法绑定到合法 ActionTemplate 时，必须以游戏规则口吻拒绝。
拒绝也应提供下一步可行路径。
```

错误拒绝示例：

```text
AI 没理解你的意思。
```

正确拒绝示例：

```text
你现在不能夜探后山：你没有灯，也没有熟路人带路。你可以先找韩叔打听夜路，或去茶棚听听最近的传闻。
```

### 新增建议模块

```text
playable_turn.py
scene_renderer.py
feedback_renderer.py
input_binder.py
```

### 新增 API

```text
GET  /worlds/{world_id}/play/state
POST /worlds/{world_id}/play/turn
GET  /worlds/{world_id}/play/scene
GET  /worlds/{world_id}/play/affordances
```

---

## 5.2 Player Progression Layer

### 目标

让玩家成长体现为“更多可做的事”，而不是单纯数值上涨。

### 六条成长线

```text
identity     身份成长：你现在被世界当成什么人
skill        技能成长：你做什么更熟练
resource     资源成长：你掌握什么筹码
relationship 关系成长：谁信你、欠你、怕你、怀疑你
knowledge    知识成长：你知道哪些线索、秘密、传闻
permission   权限成长：你能进哪里、找谁、接什么任务
```

### 第一版优先级

第一版优先实现：

```text
identity
relationship
knowledge
permission
```

技能和资源做轻量版本。

### 示例

```text
孙娘 trust +2
→ 解锁：赊药、进入药铺后院、请求治疗。

获得 knowledge: white_shadow_fears_fire
→ 解锁：带火夜探破庙。

获得 identity: sect_candidate
→ 解锁：向林砚申请外役试工。

获得 permission: sleep_at_temple
→ 解锁：夜间在破庙休息，减少体力消耗。
```

### 新增事件类型

```text
ADD_IDENTITY_TAG
REMOVE_IDENTITY_TAG
GAIN_SKILL_XP
LEVEL_SKILL
ADD_KNOWLEDGE
GRANT_PERMISSION
REVOKE_PERMISSION
CHANGE_RELATION
DELTA_RESOURCE
```

### 新增状态字段建议

```text
player.identity_tags
player.skills.{skill_id}
player.resources.{resource_id}
player.known_clues
player.permissions
npc.{npc_id}.trust.player
npc.{npc_id}.suspicion.player
faction.{faction_id}.reputation.player
```

---

## 5.3 Quest Journal / Tension Journal

### 目标

把 “Tension → Quest” 从后端机制变成玩家可理解的目标系统。

任务日志不能只显示标题，必须显示：

```text
tension 来源
当前目标
已知线索
相关 NPC
可选路线
奖励
风险
失败后果
已造成的后果
```

### Quest 数据结构建议

```json
{
  "quest_id": "investigate_white_shadow",
  "title": "调查夜庙白影",
  "source_tension_id": "white_shadow_rumor",
  "issuer_id": "lin_yan",
  "status": "active",
  "known_clues": ["white_shadow_fears_fire"],
  "objectives": [
    {"type": "visit_location", "target": "ruined_temple", "status": "open"},
    {"type": "collect_evidence", "target": "ash_trace", "status": "hidden"}
  ],
  "available_approaches": ["social", "stealth", "knowledge"],
  "rewards": ["sect_contribution", "lin_yan_trust"],
  "risks": ["night_injury", "lu_san_suspicion"],
  "evidence_refs": []
}
```

### 新增 API

```text
GET /worlds/{world_id}/play/quests
GET /worlds/{world_id}/play/tensions
GET /worlds/{world_id}/play/quests/{quest_id}/explain
```

---

## 5.4 Relationship / Faction / Permission Panel

### 目标

让玩家看到自己在小世界中的社会位置。

### 面板展示内容

```text
NPC trust / fear / debt / suspicion / respect
Faction reputation / hostility / access_level
Identity tags
Permissions
Known rumors about player
```

### 示例

```text
孙娘：信任 3，怀疑 1，愿意赊药
林砚：尊重 1，正在观察你是否可靠
鲁三：怀疑 2，听说你打听夜路
青木宗外门：候选 0/3，尚未认可
```

### 设计原则

```text
不要展示全知真相，只展示玩家可知信息。
开发者 debug mode 可以显示完整 canonical / npc / rumor scope。
```

---

## 5.5 Foreground NPC Scheduler

### 目标

让 NPC 行动成为游戏体验，而不是后台噪声。

### 三环模拟

```text
Foreground NPC：玩家同地点、同 quest、同 tension 的 3～5 个，每回合认真推演。
Midground NPC：同区域其他命名 NPC，每 2～4 回合粗推演。
Background Faction：只生成摘要事件。
```

第一版只实现 Foreground NPC。

### NPC 行动来源

```text
NPC goal
NPC memory / belief / rumor
NPC resources
relationship to player
active tension
available action templates
risk tolerance
```

### 允许的第一版 NPC 动作

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

### 必须写入事件

```text
NPC_ACTION
SPREAD_RUMOR
REQUEST_HELP
CHANGE_RELATION
ADD_MEMORY
UPDATE_TENSION
```

### 新增 API

```text
POST /worlds/{world_id}/play/npc-tick
GET  /worlds/{world_id}/play/npc-activity
```

---

## 5.6 Drama Foreground Manager v0

### 目标

不写死剧情，只决定哪个局势应该浮到前台。

### 前台容量限制

任意时刻只展示：

```text
1 条主 tension
1 条副 tension
1 条环境噪声
```

### 输入

```text
玩家最近行为
最近访问地点
最近对话 NPC
未解决 tension
任务进度
NPC 关系变化
时间压力
风险等级
教学价值
```

### 输出

```text
foreground_tension
recommended_opportunity
npc_should_approach_player
ambient_event
```

### 示例

```text
你刚向焦七打听鲁三，茶棚里立刻有人压低声音。鲁三的脚夫似乎注意到了你。
```

这不是剧情脚本，而是：

```text
player_interest: lu_san
active_tension: white_shadow_rumor
npc_suspicion: lu_san +1
foreground event: footman_notice_player
```

---

## 5.7 Explain / Timeline Panel

### 目标

把项目的 EventLog / KG / evidence 优势变成玩法。

### 玩家可问

```text
为什么药价上涨？
为什么孙娘不信任我？
为什么林砚给我委托？
白影传闻从哪里来的？
为什么后山夜路被封？
```

### 回答结构

```text
当前状态
→ 相关事件链
→ 相关 NPC 记忆 / 传闻
→ 相关 tension
→ 影响的可行动作
```

### 新增 API

```text
GET /worlds/{world_id}/play/timeline
GET /worlds/{world_id}/play/explain/state/{entity_id}/{attr}
GET /worlds/{world_id}/play/explain/quest/{quest_id}
GET /worlds/{world_id}/play/explain/rumor/{rumor_id}
```

---

## 6. Web UI 设计

## 6.1 页面布局

```text
┌────────────────────────────────────────────┐
│ 顶部：世界名 / 回合 / 时间 / 主 tension      │
├──────────────┬────────────────┬────────────┤
│ 左侧场景栏    │ 中央叙事栏       │ 右侧状态栏 │
│ 地点          │ 事件反馈         │ 角色状态   │
│ 可见 NPC      │ 对话记录         │ 任务       │
│ 地点连接      │ 世界变化摘要     │ 关系       │
│ 环境风险      │                │ 传闻       │
├──────────────┴────────────────┴────────────┤
│ 底部：推荐行动按钮 3～7 个 + 自由输入框       │
└────────────────────────────────────────────┘
```

## 6.2 必备面板

```text
Scene Panel
Action Panel
Narrative / Feedback Panel
Player Status Panel
Quest / Tension Panel
Relationship / Faction Panel
Rumor / Knowledge Panel
Timeline / Explain Panel
```

## 6.3 行动按钮与自由输入

行动按钮：

```text
稳定、规则可控、适合新手。
```

自由输入：

```text
增强沉浸，但必须映射到合法 ActionTemplate。
```

---

## 7. 失败、风险与代价

### 7.1 结果类型

```text
full_success          完全成功
success_with_cost     带代价成功
fail_forward          失败但局势前进
catastrophic_failure  灾难性失败
```

### 7.2 风险判定输入

```text
action.risk
player.skill
player.resource
npc.relation
location.danger
known_clues
permission
```

### 7.3 失败必须产生状态

错误设计：

```text
你失败了，什么也没发生。
```

正确设计：

```text
你没能进入后山，但巡夜人记住了你的脸。
```

对应事件：

```text
ACTION_FAILED
ADD_MEMORY
CHANGE_RELATION
INCREASE_TENSION
```

---

## 8. 青溪镇 30 分钟 Vertical Slice

Beta 3 必须用一个完整样板证明游戏好玩。

推荐样板：

```text
青溪镇修仙小世界
```

### 8.1 玩家前史三选一

```text
逃荒来的短工
- 初始资源：少量食物
- 熟人：韩叔
- 债务：欠茶棚饭钱
- 技能：劳作 +1
- 限制：山门不认识你

药铺外门学徒
- 初始资源：基础伤药
- 熟人：孙娘
- 债务：要完成试工
- 技能：识药 +1
- 限制：夜路胆怯

欠债的落魄猎户
- 初始资源：旧弓
- 熟人：鲁三
- 债务：欠鲁三钱
- 技能：山路 +1
- 限制：被林砚怀疑
```

### 8.2 地点

```text
镇口渡桥
药铺
茶棚
县仓
破庙
后山灵田
山门外驿道
```

### 8.3 NPC

```text
药婆孙娘：药铺、医术、旧闻、试工入口
焦七：茶棚、消息、债务、传闻扩散
宋衡：县仓、账页、妹妹病情
林砚：山门外役、立功压力、组织入口
鲁三：夜路、脚夫、地头蛇
小妮：破庙、白影真相的一半
韩叔：后山路径、欠债、风险信息
顾回：符、灵脉异常、真假试探
```

### 8.4 核心 tension

```text
药荒
- 灵田异常、药铺缺货、病人增多、药价上涨。

外役招募
- 山门给玩家上升通道，也带来势力压力。

夜庙白影
- 偷采、藏账、旧怨、传闻和夜路风险。
```

### 8.5 前 10 回合体验目标

```text
1. 玩家在茶棚听到药荒和外役招募。
2. 玩家获得一个低风险试工入口。
3. 玩家认识孙娘或焦七。
4. 玩家接触小妮或林砚。
5. 玩家得到一条半真半假的白影线索。
6. NPC 发生一次主动行动，例如鲁三脚夫盯上玩家。
7. 玩家触发一次关系变化。
8. 玩家解锁一个新 affordance。
9. 一条 tension 被前台展示。
10. 玩家形成 2～3 条可继续路线。
```

### 8.6 30 分钟结束时玩家应形成的自我叙述

```text
我是药铺线的人 / 山门线的人 / 夜路线的人。
我知道了一点秘密。
我被某人记住了。
我得罪了或吸引了某个势力。
我接下来想赌一条路。
```

这就是“我的故事”的起点。

---

## 9. Beta 3 开发阶段

## Phase 1：Playable Turn Kernel

任务：

```text
1. 新增 playable_turn.py。
2. 新增 scene_renderer.py。
3. 新增 input_binder.py。
4. 新增 feedback_renderer.py。
5. POST /worlds/{world_id}/play/turn。
6. GET /worlds/{world_id}/play/state。
7. 每回合返回 scene / affordances / feedback / changes / next_hooks。
```

验收：

```text
玩家可以不用 debug API，直接通过 play API 完成 10 回合。
每回合至少返回一个结构化 changes 列表。
非法自由输入被规则化拒绝。
```

---

## Phase 2：Progression + Quest Journal

任务：

```text
1. 添加 identity / skill / resource / knowledge / permission 数据模型。
2. 添加成长事件类型。
3. 添加 Quest Journal view。
4. Quest 展示 tension/evidence/objectives/routes/rewards/risks。
```

验收：

```text
玩家 10 回合内至少获得 1 个 knowledge、1 个 relation change、1 个 permission 或 identity tag。
Quest Journal 可以解释任务来源。
```

---

## Phase 3：Relationship / Faction / Permission Panels

任务：

```text
1. 增加 player-visible relationship projection。
2. 增加 faction attitude projection。
3. 增加 permission projection。
4. 区分 player-known 与 dev-mode full truth。
```

验收：

```text
玩家能看到至少 2 个 NPC 对自己的态度变化。
玩家看不到 canonical 之外的全知真相。
```

---

## Phase 4：Foreground NPC Scheduler

任务：

```text
1. 实现 foreground NPC selection。
2. 同地点 / 同 tension / 同 quest 的 NPC 优先。
3. 每回合推进 1～3 个 NPC action。
4. NPC action 写 EventLog。
5. NPC 行动反馈进入 play turn response。
```

验收：

```text
30 回合内至少出现 5 次 NPC 主动行动。
NPC 行动必须能追溯 goal/memory/tension。
```

---

## Phase 5：Drama Foreground v0

任务：

```text
1. 主 tension / 副 tension / ambient noise 选择。
2. PlayerInterestTracker。
3. recommended_opportunity。
4. npc_should_approach_player。
```

验收：

```text
玩家每 3～5 回合至少看到一个新机会或新压力。
前台 tension 数量不超过 2 条，避免信息过载。
```

---

## Phase 6：Explain / Timeline Productization

任务：

```text
1. Timeline API。
2. explain state。
3. explain quest。
4. explain rumor。
5. UI 展示因果链。
```

验收：

```text
玩家能解释至少一条因果链：例如为什么药价上涨 / 为什么孙娘不信任我。
```

---

## Phase 7：Qingxi Town Vertical Slice

任务：

```text
1. 将青溪镇写成 WorldSpec sample。
2. 编写专用 ActionTemplate。
3. 编写初始 tensions / quests / memories / rumors。
4. 编写前 10 回合体验测试。
5. 编写 30 分钟 playtest script。
```

验收：

```text
玩家能完整游玩 30 分钟。
10 回合内有明确目标。
30 分钟内至少 5 次可见世界变化。
至少 1 条路线让玩家想继续。
```

---

## 10. Beta 3 推荐 Codex Issue 顺序

```text
PG-01 Add Playable Turn Kernel and play APIs
PG-02 Add scene/action/feedback response model
PG-03 Add player progression events and projections
PG-04 Add Quest Journal and Tension Journal views
PG-05 Add relationship/faction/permission player-visible panels
PG-06 Add Foreground NPC Scheduler
PG-07 Add Drama Foreground Manager v0
PG-08 Add Explain/Timeline player-facing APIs
PG-09 Add Qingxi Town WorldSpec vertical slice
PG-10 Add playability evaluation suite
```

---

## 11. Beta 3 评估指标

### 11.1 系统指标

```text
play_turn_success_rate >= 95%
invalid_action_rejection_rate >= 95%
eventlog_write_rate = 100%
replay_consistency = 100%
canonical_contamination_rate = 0%
npc_privileged_knowledge_rate <= 5%
quest_traceability_rate >= 90%
```

### 11.2 可玩性指标

```text
first_goal_time <= 3 turns
first_relation_change_time <= 5 turns
first_new_affordance_time <= 8 turns
visible_world_changes_in_30min >= 5
npc_active_events_in_30min >= 5
player_can_recall_2_npcs = true
player_can_explain_1_causal_chain = true
player_has_2_continuation_routes = true
```

### 11.3 体验判断

一个 run 开始好玩，应满足：

```text
玩家知道自己是谁。
玩家知道现在可以做什么。
玩家知道至少一个短期目标。
玩家相信行动会改变世界。
玩家记得至少两个 NPC。
玩家已经获得或失去某种社会位置。
玩家愿意继续这个 run，而不是只想重开看 AI 生成新文本。
```

---

## 12. Beta 3 不做内容

暂时不要做：

```text
1. Unity / Unreal / Godot 客户端。
2. 复杂 2D 地图移动。
3. 大规模战斗系统。
4. 复杂功法树。
5. 全 NPC 全时段深度模拟。
6. 宏观经济系统。
7. 多人联机。
8. 生产级云部署。
```

这些都应该在 Web 文字版证明好玩之后再考虑。

---

## 13. 完成定义

Beta 3 完成时，必须能演示：

```text
1. 玩家通过 Web UI 或 play API 进入一个 WorldSpec 生成的小世界。
2. 玩家每回合看到场景、推荐行动、状态、任务、关系和反馈。
3. 玩家自由输入必须被绑定到合法 ActionTemplate 或被规则化拒绝。
4. 玩家 10 回合内获得明确目标和至少一个成长反馈。
5. NPC 会主动行动，并改变关系、传闻、任务或 tension。
6. Quest Journal 能展示任务从哪条 tension 来。
7. Relationship/Faction Panel 能显示玩家社会位置变化。
8. Explain/Timeline 能解释至少一条因果链。
9. 青溪镇 Demo 可连续玩 30 分钟。
10. 世界 replay 后状态一致，rumor / subjective memory 不污染 canonical。
```

一句话完成标准：

> 玩家能在一个 AI 生成的小世界里，以低起点身份进入，通过每回合合法行动改变局势、积累关系/知识/权限，最终形成“这是我自己的故事”的体验。
