# Game-World-KG 开发推进详细方案（基于研究报告）

## 目标
- 将 game-world-kg 打造成稳定生成、可验证、可微调、可运行、可玩 30 分钟的 AI 小世界引擎。
- 保证 EventLog 作为真值源，RuleEngine 执行合法动作，LLM 仅生成候选。

## 开发阶段

### Phase 1：世界生成稳定化
- 补齐 WorldSpec prompt 字段契约
- 强化 validator preflight
- 保存原始 raw draft
- 验收标准：坏 JSON 不丢，prompt schema 漂移减少，validation issue 可操作

### Phase 2：WorldSpec Draft / Candidate 系统
- 建立 Candidate Store 与 Raw Draft Store
- Parse / Validate / Adopt 分离
- 支持重复 validate，candidate 未 valid 前不能 bootstrap

### Phase 3：Bootstrap / Replay / Projection 稳定化
- 只接受 valid candidate bootstrap
- bootstrap transaction + idempotency
- replay / rebuild consistency
- 验收标准：valid candidate 可 bootstrap，状态一致，Kuzu/Chroma 查询正常

### Phase 4：ActionTemplate Runtime + 输入绑定
- 完整 ActionTemplate runtime: PredicateEvaluator, EffectExecutor, AffordanceEngine
- 输入绑定: Intent Parser + Binder，非法输入规则化拒绝
- 验收标准：初始场景 3-7 个 affordances，自由输入绑定成功或规则拒绝

### Phase 5：成长层 + Fail-forward
- 玩家成长：identity, relationship, knowledge, permission
- Fail-forward: full_success, success_with_cost, fail_forward, catastrophic_failure
- 验收标准：10 回合内至少 1 次成长反馈，失败产生真实状态变化

### Phase 6：NPC 自运行深化
- Foreground / Midground / Background NPC tick
- 谣言传播机制 SPREAD_RUMOR/WITNESS_EVENT
- 关系属性 fear/debt/respect 写入事件和状态
- 验收标准：30 回合内至少 5 次 NPC 行动，谣言传播，关系属性真实变化

### Phase 7：Tension / Quest / Drama 深化
- 扩展 Tension 模型：stake, deadline, sponsors, blockers, player_touchpoints
- QuestGenerator 泛化，支持多解法、多 sponsor/blocker、failure consequence
- Drama 1+1+1，4 层反馈
- 验收标准：每个 quest 可追溯 tension/evidence，多解法，foreground 1+1+1，变化 4 层

### Phase 8：Beta 3 Playable Game Layer + Qingxi Vertical Slice
- UI: Scene Panel, Action Panel, Narrative Panel, Player Status, Quest/Tension, Relationship/Faction, Rumor/Knowledge, Timeline/Explain
- Qingxi Town 30 分钟剧本测试
- 验收标准：30 分钟可玩，10 回合内有目标和成长反馈，至少 5 次可见世界变化

## 优先级顺序
1. WorldSpec 稳定生成 + raw draft 保存
2. Candidate Store + validate / parse
3. Bootstrap / replay / rebuild
4. ActionTemplate runtime + 输入绑定
5. 成长层 + Fail-forward
6. NPC 自运行深化
7. Tension / Quest / Drama 深化
8. Beta 3 Playable Demo

## 不做内容（暂时）
- Agent patch 世界制作器
- LangGraph 外壳
- PilotDeck
- MCP 工具化
- 大规模战斗、多人联机、复杂功法树