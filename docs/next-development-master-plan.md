# Game-World-KG 开发推进详细方案（扩充详细版，严格基于研究报告）

## 一、项目目标
- 构建稳定生成、可验证、可微调、可运行、可玩 30 分钟的 AI 小世界引擎
- EventLog 为世界真值源，RuleEngine 执行合法动作，LLM 仅生成候选
- 遵循 Beta 2/Beta 3 研究报告，优先完成世界生成、验证和可运行系统

## 二、开发阶段及详细任务

### Phase 1：世界生成稳定化
- **任务**：
  - 补齐 WorldSpec prompt 字段契约：scale、character.goals、tension.description、background_lore、faction.relations 等
  - 增加正反例示范，确保模型区分合法/非法字段
  - 强化 Validator，增加 issue code，例如 character_goal_missing_goal_id、background_lore_must_be_list
  - 保存原始 raw draft，支持多次 parse/validate
- **产出**：raw draft, validation report, prompt 模板
- **验收标准**：生成 JSON 不丢失，字段契约漂移减少，validation issue 可操作

### Phase 2：WorldSpec Draft / Candidate 系统
- **任务**：
  - 建立 Candidate Store 与 Raw Draft Store
  - Parse / Validate / Adopt 分离，candidate 未 valid 前不能 bootstrap
  - 支持重复 validate，减少模型多次生成
- **产出**：worldspec_raws, worldspec_candidates, parse/validate trace
- **验收标准**：每次生成都有 raw draft，candidate 可重复 validate

### Phase 3：Bootstrap / Replay / Projection 稳定化
- **任务**：
  - Bootstrap 只接受 validated candidate
  - 实现幂等 bootstrap transaction
  - replay / rebuild consistency 保证 SQLite/Kuzu/Chroma 状态一致
- **验收标准**：valid candidate 可 bootstrap，状态一致

### Phase 4：ActionTemplate Runtime + 输入绑定
- **任务**：
  - 完整 ActionTemplate runtime：PredicateEvaluator, EffectExecutor, AffordanceEngine
  - 输入绑定：Intent Parser + Binder，非法输入规则化拒绝并提供下一步建议
- **验收标准**：初始场景 3-7 个 affordances，自由输入绑定成功或规则拒绝

### Phase 5：成长层 + Fail-forward
- **任务**：
  - 玩家成长：identity, relationship, knowledge, permission；做什么长什么
  - Fail-forward：full_success, success_with_cost, fail_forward, catastrophic_failure
- **验收标准**：玩家 10 回合内至少 1 次成长反馈，失败产生真实状态变化

### Phase 6：NPC 自运行深化
- **任务**：
  - Foreground / Midground / Background NPC tick
  - 谣言传播机制：SPREAD_RUMOR/WITNESS_EVENT
  - 关系属性：fear/debt/respect 写入事件和状态
- **验收标准**：30 回合内至少 5 次 NPC 行动，谣言传播生效，关系属性真实变化

### Phase 7：Tension / Quest / Drama 深化
- **任务**：
  - 扩展 Tension 模型：stake, deadline, sponsors, blockers, player_touchpoints
  - QuestGenerator 泛化，支持多解法、多 sponsor/blocker、failure consequence
  - Drama 1+1+1，4 层反馈：narrative / mechanics / social / world
- **验收标准**：Quest 可追溯 tension/evidence，多解法，foreground 1+1+1，反馈分 4 层

### Phase 8：Beta 3 Playable Game Layer + Qingxi Vertical Slice
- **任务**：
  - UI: Scene Panel, Action Panel, Narrative Panel, Player Status, Quest/Tension, Relationship/Faction, Rumor/Knowledge, Timeline/Explain
  - Qingxi Town 30 分钟剧本测试
- **验收标准**：30 分钟可玩，前 10 回合有目标和成长反馈，至少 5 次可见世界变化

## 三、阶段依赖关系
- Phase 1 → Phase 2 → Phase 3 → Phase 4
- Phase 4 → Phase 5 / Phase 6 / Phase 7
- Phase 5 + 6 + 7 → Phase 8

## 四、近期优先级
- **P0**：保存 raw draft，完善 prompt schema，增强 validator
- **P1**：Candidate parse/validate，人工修复入口，稳定 bootstrap/replay
- **P2**：ActionTemplate runtime 补全，Intent Parser + Binder
- **P3**：成长层 + Fail-forward，Quest/Tension 多解法
- **P4**：NPC 三层、谣言传播、Drama 1+1+1、4 层反馈
- **P5**：Beta 3 Playable Demo，青溪镇 30 分钟 vertical slice

## 五、暂不做内容
- Agent patch 世界制作器
- LangGraph 外壳
- PilotDeck 工作台
- MCP 对外工具化
- 大规模战斗、多人联机、复杂功法树

## 六、验收标准总结
- Beta 2：生成稳定，candidate 验证通过，bootstrap 正确，NPC tick 合理，事件可回放
- Beta 3：可玩 30 分钟，玩家成长、自由行动、Quest/Drama/Feedback 正确，Timeline/Explain 可追溯因果链
