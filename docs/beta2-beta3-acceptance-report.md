# Game-World-KG Beta 2 / Beta 3 验收报告与下一步任务

> 本文档用于按照研究报告、`docs/next-development-master-plan.md` 与 `docs/master-plan-completion-audit.md` 对当前 main 分支进行验收。
>
> 重要原则：本文档不是“宣布完成”的文档，而是“验收执行表”。所有状态必须由代码、测试、playtest 记录或可复现命令支撑。
>
> 本文档不引入 Agent Patch、LangGraph、PilotDeck、MCP、游戏引擎表现层等新方向。验收范围严格限定在研究报告主线：WorldSpec、EventLog、RuleEngine、ActionTemplate、NPC、Tension、Quest、Drama、Memory Scope、Replay/Explain、Playable Layer。

---

## 1. 验收版本

当前验收基线：

```text
main / origin/main
HEAD: 83072b3 feat: ACT-05 — template_only 模式验收
验收参考起点: d29c59a fix: repair raw draft parsing and feedback/event consistency
```

本轮新增关键提交：

```text
299d840 feat: P3 系统深化验证
3df790a feat: 补齐 fail-forward 全谱系测试和场景一致性验收
150c8c0 feat: NPC midground 去随机化 + goal-driven 选择验证
1496d6a feat: Tension scanner 泛化
a5d8202 feat: Timeline/Explain 因果链端到端验证
83072b3 feat: ACT-05 — template_only 模式验收
```

---

## 2. 研究报告核心原则验收

| 原则 | 验收状态 | 当前证据 | 后续动作 |
|---|---|---|---|
| EventLog 是 source of truth | 部分通过 | 世界变化主要通过 EventLog / EventRecord 进入状态投影 | 补 replay state hash / rebuild 一致性测试 |
| Kuzu / Chroma 只是投影 | 需要测试证明 | 已有投影相关服务，但需证明可从 EventLog 重建 | 补 Kuzu / Chroma rebuild 验收 |
| LLM 只生成候选，不直接改 canonical | 基础通过 | Raw Draft / Candidate 生命周期已建立，raw parse 不再重新调用 LLM | 补 endpoint 级 raw parse 测试 |
| ActionTemplate 是可执行 DSL | 基本通过 | template_only 模式、Predicate/Effector、cost/fail/catastrophic effect plan 已接入 | 补生成世界路径的 template_only 验收 |
| Quest 来自 Tension | v0+ | Tension scanner 泛化、Quest alternatives 测试已新增 | 补多世界、多 tension 样本验证 |
| NPC 行动经过规则系统 | v0+ | NPC action 共享 validate_and_resolve_action 路径 | 补 NPC explain 到 goal/memory/tension 的端到端测试 |
| Memory Scope 不污染 canonical | 部分通过 | rumor/npc scope guard 已有 | 补 rumor propagation → no canonical contamination 验收 |
| 可回放 / 可解释 | 部分通过 | Timeline/Explain 因果链测试已新增 | 补 replay/rebuild + Explain 串联验收 |

---

## 3. Beta 2 验收

Beta 2 的目标：输入一个世界想法，生成可验证 WorldSpec，经 Bootstrap 写入 EventLog，并能通过 replay / rebuild / explain 证明世界状态一致、任务来源可追溯、记忆 scope 不污染 canonical。

### 3.1 WorldSpec 生成稳定化

验收目标：

```text
- LLM raw 输出必须保存。
- JSON parse / Pydantic / WorldSpecValidator 错误可定位。
- Candidate 可以重复 validate。
- invalid candidate 不应直接 bootstrap。
```

当前状态：**部分通过**

当前证据：

```text
- worldspec_raw_drafts / worldspec_candidates 已有。
- RawDraftRepository / CandidateRepository 已有。
- /v1/worldspec/raw/latest、/raw/{id}、/raw/{id}/parse 已有。
- raw parse 已修复为解析已保存 raw_text，不再调用 LLM。
```

仍需验收：

```text
- API 级测试：raw parse endpoint 不调用 LLM。
- JSON 可 parse 但 Pydantic 失败时，是否保存 invalid_schema candidate。
- 同一批 world ideas 的 valid rate / fallback rate 统计。
```

建议测试：

```text
pytest tests/test_worldspec_raw_drafts.py -v
新增：test_raw_parse_endpoint_uses_saved_raw_text_not_llm
新增：test_json_parse_success_but_schema_invalid_is_preserved_for_repair
新增：test_worldspec_generation_stability_batch_metrics
```

验收结论：

```text
当前为“生成稳定化基础通过”，但不能宣称生成稳定性完全完成。缺少批量 valid rate 指标。
```

---

### 3.2 Raw Draft / Candidate 生命周期

验收目标：

```text
Raw Draft → Parse → Candidate → Validate → Repaired Candidate → Validated Candidate → Bootstrap
```

当前状态：**基础通过**

当前证据：

```text
- raw draft store 已落地。
- candidate store 已落地。
- repaired-json API 已有。
- candidate validate API 已有。
```

仍需验收：

```text
- Candidate repaired-json 目前偏覆盖式，缺 version/history/diff。
- Candidate 未 valid 不能进入正式 bootstrap，需要明确测试。
```

建议测试：

```text
pytest tests/test_candidate_history.py -v
新增：test_invalid_candidate_cannot_bootstrap_from_candidate_lifecycle
新增：test_submit_repaired_json_keeps_previous_candidate_version_or_history
```

验收结论：

```text
Beta 2 最小生命周期基础通过；制作器级版本历史未完成，但不阻塞 Beta 2 最小验收。
```

---

### 3.3 Bootstrap / Replay / Projection

验收目标：

```text
- Validated Candidate 可 bootstrap。
- Invalid Candidate 被拒绝。
- Bootstrap 幂等。
- Replay 后 state 一致。
- Kuzu / Chroma 可从 EventLog 重建。
```

当前状态：**部分通过 / 需要测试证明**

当前证据：

```text
- bootstrap_worldspec 基础链路存在。
- bootstrap_runs 表存在。
- 新增 tests/test_bootstrap_integrity.py。
```

仍需验收：

```text
- replay state hash 与当前 state 是否一致。
- Kuzu rebuild 后节点/边是否一致。
- Chroma rebuild 后记忆/背景/证据是否可召回。
- Bootstrap 失败是否事务回滚。
```

建议测试：

```text
pytest tests/test_bootstrap_integrity.py -v
新增：test_replay_after_bootstrap_matches_projected_state
新增：test_bootstrap_transaction_rolls_back_on_failure
新增：test_kuzu_rebuild_after_bootstrap_matches_eventlog_projection
新增：test_chroma_rebuild_after_bootstrap_recalls_memory_and_lore
```

验收结论：

```text
Bootstrap 基础通过；完整 replay/rebuild/projection 验收未最终通过。
```

---

### 3.4 Quest 来源与 Evidence

验收目标：

```text
- Quest 必须有 tension_id。
- Quest 必须有 evidence。
- objective 必须是结构化对象。
- Quest route 必须能映射到可执行 action / affordance。
```

当前状态：**v0+ 通过**

当前证据：

```text
- Tension scanner 泛化提交已进入 main。
- tests/test_tension_generic.py、tests/test_tension_quest.py、tests/test_quest_alternatives.py 已新增。
```

仍需验收：

```text
- 多世界样本下是否仍能稳定生成可执行 quest。
- alternatives 是否都能映射到真实 affordance。
- reward / failure consequence 是否可执行。
```

建议测试：

```text
pytest tests/test_tension_generic.py tests/test_tension_quest.py tests/test_quest_alternatives.py -v
新增：test_quest_alternative_routes_map_to_available_affordances_in_generated_world
新增：test_quest_failure_consequence_compiles_to_effects
```

验收结论：

```text
Quest/Tension 主链 v0+ 通过，但泛化质量需要多世界验证。
```

---

### 3.5 Memory Scope / Canonical 污染防线

验收目标：

```text
- NPC belief / suspicion / rumor 不能写 canonical。
- rumor 传播必须保持 rumor 或 npc scope。
- Explain 必须能显示 source/evidence。
```

当前状态：**部分通过**

当前证据：

```text
- rumor scope guard 已接入。
- NPC / rumor 相关测试已增加。
```

仍需验收：

```text
- Rumor propagation 后 canonical state 不变。
- NPC subjective memory 不应被 player 直接读取。
- Explain 中能看到 rumor 的 evidence refs。
```

建议测试：

```text
pytest tests/test_npc_three_tier.py tests/test_npc_explain.py -v
新增：test_rumor_propagation_does_not_write_canonical_state
新增：test_player_cannot_read_private_npc_memory_without_evidence
新增：test_explain_rumor_chain_contains_source_memory
```

验收结论：

```text
Scope 防线有基础，但仍需 canonical contamination 专项验收。
```

---

## 4. Beta 3 验收

Beta 3 的目标：玩家可以连续游玩一个小世界，在 10 回合内获得目标、成长、NPC 互动、任务来源和世界变化；30 回合或 30 分钟后仍有继续路线，并能通过 Explain/Timeline 解释关键因果链。

### 4.1 ActionTemplate Runtime + 输入绑定

验收目标：

```text
- 当前场景有 3-7 个推荐 affordances。
- 玩家按钮行动走 ActionTemplate。
- 自由输入只能绑定当前合法 affordance。
- 非法输入规则化拒绝。
- template_only 模式不依赖 hardcoded demo handler。
```

当前状态：**基本通过**

当前证据：

```text
- ACT-05 template_only 模式验收已提交。
- tests/test_template_only_mode.py 已新增。
- tests/test_input_binding.py 已增强。
- target mismatch fallback 已修复。
```

仍需验收：

```text
- 生成世界路径是否也能 template_only，而非仅 demo/seed。
- 每个初始场景 affordances 是否稳定在合理范围。
```

建议测试：

```text
pytest tests/test_template_only_mode.py tests/test_input_binding.py tests/test_action_template.py -v
新增：test_generated_world_template_only_first_scene_affordances
新增：test_no_hardcoded_demo_action_in_template_only_mode
```

验收结论：

```text
ActionTemplate Runtime + 输入绑定基本通过；生成世界 template_only 路径仍需补验收。
```

---

### 4.2 成长层

验收目标：

```text
- identity / relationship / knowledge / permission 四主线必须产生反馈。
- 至少一个新 affordance 由成长解锁。
- 成长结果进入 player panel / feedback layers。
```

当前状态：**v0+ 通过**

当前证据：

```text
- PLAYER_GROWTH 使用 growth_lines。
- FeedbackRenderer 已能识别 identity/relationship/knowledge/permission/skill。
- has_identity_tag / has_permission / has_knowledge predicate 已接入。
- tests/test_growth_affordance.py、tests/test_growth_lines.py 已新增。
```

仍需验收：

```text
- 连续 10 回合内是否自然获得成长。
- 成长解锁是否在真实 playable flow 中出现。
- 玩家是否能通过 UI/API 理解成长带来的变化。
```

建议测试：

```text
pytest tests/test_growth_affordance.py tests/test_growth_lines.py -v
新增：test_qingxi_growth_unlocks_new_action_within_10_turns
新增：test_player_panel_shows_identity_knowledge_permission_relationship_growth
```

验收结论：

```text
成长系统 v0+ 通过；还需 10-turn playable flow 证明自然发生。
```

---

### 4.3 Fail-forward

验收目标：

```text
- full_success / success_with_cost / fail_forward / catastrophic_failure 均可触发。
- success_with_cost 产生成本事件。
- fail_forward 产生局势推进事件。
- catastrophic_failure 只用于高风险行动。
- outcome_type 和 effect plan 一致。
```

当前状态：**机制初版通过**

当前证据：

```text
- ActionTemplate 已新增 cost_effects / fail_effects / catastrophic_effects。
- validate_and_resolve_action 已改为先 compute outcome，再选择 effect plan。
- tests/test_outcome_spectrum.py 已新增。
- tests/test_scene_consistency.py 已新增。
```

仍需验收：

```text
- OutcomeResolver 仍是简单 risk matrix，不够世界状态驱动。
- fail/catastrophic fallback 到 success effects + cost effects 的策略是否符合剧情体验，需要 playtest。
- tension 推进、NPC 记忆、关系变化是否自然。
```

建议测试：

```text
pytest tests/test_outcome_spectrum.py tests/test_scene_consistency.py -v
新增：test_fail_forward_increases_tension_or_creates_clue
新增：test_catastrophic_failure_does_not_apply_success_reward_when_catastrophic_effects_exist
新增：test_success_with_cost_applies_success_and_cost_events
```

验收结论：

```text
Fail-forward 从 v0 label 升级为 effect plan 初版，Beta 3 机制验收初步通过；体验质量未最终通过。
```

---

### 4.4 NPC 三层自运行

验收目标：

```text
- Foreground NPC 每回合认真推演 1-3 个。
- Midground NPC 每 2-4 回合粗粒度推进。
- Background Faction 写 FACTION_ACTIVITY / SUMMARY_EVENT。
- NPC 行动可 explain 到 goal / memory / tension。
- rumor propagation 不污染 canonical。
```

当前状态：**v0+ 通过**

当前证据：

```text
- NPC midground 去随机化 + goal-driven 选择验证已提交。
- tests/test_npc_goal_driven.py 已新增。
- tests/test_npc_three_tier.py 已新增。
- tests/test_npc_explain.py 已新增。
```

仍需验收：

```text
- 30 回合内是否自然出现至少 5 次 NPC active events。
- NPC explain 是否稳定展示 goal / memory / tension。
- Midground / background 是否影响任务、谣言、关系、资源。
```

建议测试：

```text
pytest tests/test_npc_goal_driven.py tests/test_npc_three_tier.py tests/test_npc_explain.py -v
新增：test_30_turns_produce_at_least_5_npc_active_events
新增：test_midground_event_changes_rumor_or_relation
新增：test_background_faction_event_affects_tension_or_resource
```

验收结论：

```text
NPC 三层自运行 v0+ 通过；社会模拟深度和长回合稳定性未最终通过。
```

---

### 4.5 Drama 1+1+1 与四层反馈

验收目标：

```text
- Drama 输出 main_tension / side_tension / ambient_noise。
- main/side/ambient 不能只是 scored top-N。
- Feedback 输出 narrative / mechanics / social / world 四层。
- 每回合变化能让玩家知道“世界真的变了”。
```

当前状态：**初版通过**

当前证据：

```text
- DramaManager 已有 semantic classification。
- tests/test_drama_semantic.py 已新增。
- tests/test_four_layer_feedback.py 已新增。
- FeedbackRenderer 已输出 layers。
```

仍需验收：

```text
- 真实 playtest 中 main/side/ambient 是否符合玩家感受。
- 四层反馈是否有足够信息密度，而非只是一堆日志。
- outcome / growth / quest / npc activity 是否都正确归层。
```

建议测试：

```text
pytest tests/test_drama_semantic.py tests/test_four_layer_feedback.py -v
新增：test_qingxi_feedback_layers_have_mechanics_social_world_after_key_turn
新增：test_drama_main_tension_changes_after_player_interest_changes
```

验收结论：

```text
Drama 与四层反馈初版通过；需要 playtest 调参。
```

---

### 4.6 Timeline / Explain 因果链

验收目标：

```text
- 玩家能解释至少一条因果链。
- 因果链能从 action → event → state_delta → quest/tension/feedback。
- Explain 不依赖 LLM 幻觉，而依赖 EventLog/evidence。
```

当前状态：**部分通过 / 需要端到端证明**

当前证据：

```text
- Timeline/Explain 因果链端到端验证已提交。
- tests/test_causal_chain.py 已新增。
```

仍需验收：

```text
- 真实 play flow 中 explain 是否能解释玩家关心的问题。
- Quest 出现原因、NPC 态度变化、权限解锁原因是否都能 explain。
```

建议测试：

```text
pytest tests/test_causal_chain.py -v
新增：test_explain_why_permission_was_unlocked
新增：test_explain_why_npc_trust_changed
新增：test_explain_why_quest_started_from_tension
```

验收结论：

```text
Explain 因果链测试已有；产品级可解释性仍需真实 playtest 验证。
```

---

## 5. 真实 Playtest 验收

### 5.1 Qingxi 10-turn 验收

验收目标：

```text
第 1-3 回合：玩家知道自己是谁、在哪、能做什么。
第 1-5 回合：玩家获得至少一个短期目标。
第 1-8 回合：玩家获得至少一个成长反馈。
第 1-10 回合：至少一次 NPC 主动行动。
第 1-10 回合：至少一次关系/知识/权限/tension 变化。
第 1-10 回合：至少一个 quest 能追溯到 tension/evidence。
```

当前状态：**待执行 / 需记录结果**

建议新增测试：

```text
tests/test_qingxi_acceptance_10_turn.py
```

建议测试内容：

```text
- seed Qingxi world。
- 执行 10 个脚本化但合法的 player actions。
- 每回合断言 affordances 非空。
- 10 回合内断言 growth_lines 出现。
- 10 回合内断言 NPC active event 出现。
- 10 回合内断言 quest/tension 有 evidence。
- 10 回合内断言 feedback layers 不为空。
```

验收结论：

```text
未最终通过。必须补测试和运行记录。
```

---

### 5.2 Qingxi 30-turn / 30-minute 验收

验收目标：

```text
- 至少 5 次可见世界变化。
- 至少 5 次 NPC active events。
- 至少 1 条 Explain causal chain。
- 至少 2 条继续路线。
- replay 后状态一致。
- rumor / subjective memory 不污染 canonical。
```

当前状态：**待执行 / 需记录结果**

建议新增测试：

```text
tests/test_qingxi_acceptance_30_turn.py
```

建议测试内容：

```text
- seed Qingxi world。
- 连续执行 30 回合。
- 统计 EventLog 中 MOVE_ENTITY / CHANGE_RELATION / SET_STATE / ADD_MEMORY / ADD_TENSION / START_QUEST / FACTION_ACTIVITY。
- 断言 NPC active events >= 5。
- 断言 visible world changes >= 5。
- 断言 at least 2 continuation hooks / route options。
- 断言 Explain causal chain 可返回。
- 断言 replay 后 state 一致。
```

验收结论：

```text
未最终通过。必须补测试和真实 playtest 记录。
```

---

## 6. 当前最终判定

### 6.1 可以判定通过的内容

```text
- Raw Draft / Candidate 基础生命周期。
- raw parse 不再重新生成。
- ActionTemplate Runtime 基础链路。
- template_only 模式初步验收。
- 输入绑定 target mismatch 防线。
- Fail-forward effect plan 初版。
- Growth 四主线 v0+。
- NPC 三层自运行 v0+。
- Drama 1+1+1 语义分类初版。
- 四层反馈初版。
- Tension scanner / Quest alternatives v0+。
- Timeline/Explain 因果链测试雏形。
```

### 6.2 不能判定最终通过的内容

```text
- 研究报告整体完成。
- Beta 2 replay/rebuild/projection 最终验收。
- Beta 3 真实 30 分钟可玩 Demo。
- 多世界生成稳定率。
- 多世界 tension→quest 泛化质量。
- NPC 社会模拟长期稳定性。
- Player-facing UI 可玩体验。
```

### 6.3 当前一句话结论

```text
当前项目已从“结构接入 v0”推进到“核心机制具备验收条件”。
但研究报告和 Beta 2 / Beta 3 完成定义尚未最终通过。
下一步应停止扩系统，集中执行验收测试、真实 playtest 和缺口修复。
```

---

## 7. 下一步任务清单

## P0：补验收测试，不再扩新系统

### P0-01：API 级 raw parse 验收

目标：证明 raw parse endpoint 只解析保存文本，不调用 LLM。

任务：

```text
- 新增 tests/test_worldspec_raw_parse_api.py。
- 构造 raw_draft.raw_text 为合法 JSON。
- 使用会 raise 的 LLM fake client。
- 调用 /v1/worldspec/raw/{raw_id}/parse。
- 断言 parse_success=True。
- 断言 candidate.spec_json 来自 raw_text。
```

完成标准：

```text
pytest tests/test_worldspec_raw_parse_api.py -v 通过。
```

---

### P0-02：Bootstrap replay/rebuild/idempotency 验收

目标：证明 EventLog 真值链可回放、可重建、可幂等。

任务：

```text
- 扩展 tests/test_bootstrap_integrity.py。
- 验证同一 candidate/spec_hash 重复 bootstrap 不重复创建有效 world。
- 验证 bootstrap 失败时 transaction rollback。
- 验证 replay 后 state 与当前 projected state 一致。
- 如 Kuzu/Chroma 在测试环境可用，加入 rebuild 验收；不可用则标记 skip 并说明原因。
```

完成标准：

```text
pytest tests/test_bootstrap_integrity.py -v 通过。
```

---

### P0-03：Candidate repaired-json version/history

目标：避免修复 candidate 时覆盖历史，保留可审计链路。

任务：

```text
- 设计 candidate_history 或 candidate_versions。
- submit-repaired-json 后保留 old_spec_json / new_spec_json / validation_report / created_at。
- 不必做 Agent patch。
- 只支持人工 JSON 修复历史。
```

完成标准：

```text
pytest tests/test_candidate_history.py -v 通过。
```

---

## P1：Beta 2 最终验收

### P1-01：WorldSpec 批量生成稳定率

目标：用数据证明生成稳定性。

任务：

```text
- 准备 10-20 个世界 idea。
- 对每个 idea 运行 generate_worldspec。
- 统计 raw_saved_rate、json_parse_rate、pydantic_valid_rate、validator_valid_rate、fallback_rate。
- 输出到 docs/worldspec-generation-stability-report.md。
```

完成标准：

```text
- raw_saved_rate = 100%。
- json_parse_rate / validator_valid_rate 有明确数值。
- fallback 不再掩盖失败原因。
```

当前状态：**部分通过**

当前证据：

- `scripts/eval_worldspec_generation.py` 已修复，使用真实 DB 初始化 + `build_llm_client_from_env()`
- 2026-05-29 使用 AnthropicClient 对 10 个 world idea 进行真实 LLM 批量生成
- 报告输出至 `docs/worldspec-generation-stability_20260529_135521.{csv,md}`

实测结果：

| 指标 | 数值 | 比率 |
|---|---|---|
| raw_saved | 10/10 | 100% |
| json_parse_success | 5/10 | 50% |
| pydantic_valid | 10/10 | 100% |
| validator_valid | 10/10 | 100% |
| fallback_used | 5/10 | 50% |
| errors | 0/10 | 0% |

验收结论：P1-01 部分通过，final valid 100%，LLM direct parse 50%。瓶颈在 JSON parse，详见 `docs/worldspec-generation-failure-analysis.md`。

---

### P1-02：Memory Scope 污染验收

目标：证明 rumor/npc/player/faction/canonical 隔离。

任务：

```text
- 新增 tests/test_memory_scope_acceptance.py。
- 触发 NPC suspicion / rumor propagation。
- 断言 canonical 未写入 subjective belief。
- 断言 rumor memory 有 evidence_refs。
- 断言 player 不能直接读取 private npc memory。
```

完成标准：

```text
pytest tests/test_memory_scope_acceptance.py -v 通过。
```

---

## P2：Beta 3 10-turn / 30-turn 验收

### P2-01：Qingxi 10-turn Acceptance

目标：证明游戏开始阶段可玩。

任务：

```text
- 新增 tests/test_qingxi_acceptance_10_turn.py。
- 使用真实 affordance 选择，而不是硬编码不存在的 action_id。
- 每回合记录 scene / action / feedback / changes / quests / tensions / npc_activity。
- 断言 10 回合内：
  - affordances 始终非空；
  - 至少一次 growth；
  - 至少一次 relationship/knowledge/permission/tension 变化；
  - 至少一次 NPC active event；
  - 至少一个 quest 有 tension_id/evidence；
  - feedback layers 非空。
```

完成标准：

```text
pytest tests/test_qingxi_acceptance_10_turn.py -v 通过。
```

---

### P2-02：Qingxi 30-turn Acceptance

目标：证明连续游玩不是几回合后断掉。

任务：

```text
- 新增 tests/test_qingxi_acceptance_30_turn.py。
- 连续运行 30 turn。
- 记录可见世界变化、NPC active events、quest updates、relationship changes、tension updates。
- 断言：
  - visible_world_changes >= 5；
  - npc_active_events >= 5；
  - at least one explain causal chain；
  - at least two continuation routes；
  - replay consistency；
  - no canonical contamination from rumor。
```

完成标准：

```text
pytest tests/test_qingxi_acceptance_30_turn.py -v 通过。
```

---

### P2-03：手动 Playtest 日志

目标：验证测试之外的真实体验。

任务：

```text
- 新增 docs/playtests/qingxi-30min-playtest-001.md。
- 记录 30 分钟人工游玩。
- 每 3-5 回合记录：玩家目标、选择、系统反馈、是否知道下一步、是否感觉世界变化。
- 记录卡点：行动不清楚、反馈不懂、NPC 没存在感、任务路线断裂。
```

完成标准：

```text
至少 1 份真实 playtest 日志完成，并反向生成修复任务。
```

---

## P3：机制深化修复

### P3-01：Fail-forward 体验深化

目标：让 effect plan 不只是测试通过，而是游戏体验合理。

任务：

```text
- 审查 high-risk action 的 catastrophic_effects，确保不会同时给成功奖励。
- fail_forward 应至少产生一个 clue / relation / tension / memory 推进。
- success_with_cost 应明确消耗资源或增加风险。
- outcome 文案进入四层反馈。
```

完成标准：

```text
- test_fail_forward_increases_tension_or_creates_clue 通过。
- test_catastrophic_failure_does_not_apply_success_reward_when_catastrophic_effects_exist 通过。
```

---

### P3-02：NPC Explain 深化

目标：NPC 行为必须可解释，不只是事件存在。

任务：

```text
- NPC action event 增加 evidence_refs。
- Explain 输出包含：goal、memory、tension、relationship 中至少一种原因。
- Midground/background 事件也能 explain 到 faction/tension。
```

完成标准：

```text
pytest tests/test_npc_explain.py -v 通过，并新增端到端 explain 测试。
```

---

### P3-03：Quest 多解法真实可执行

目标：alternatives 不是字段，而是真路线。

任务：

```text
- 每个 quest alternative route 至少映射到一个 available affordance 或 objective action。
- route 完成后 quest objective 能推进。
- failure consequence 能执行 effect。
```

完成标准：

```text
pytest tests/test_quest_alternatives.py -v 通过，并新增 route-to-affordance 测试。
```

---

## P4：UI 前置验收

只有 P2 基本通过后，再进入 UI 实现。

UI 前置条件：

```text
- play_turn response 已稳定包含 scene / affordances / feedback layers / player / quests / tensions / relationships / npc_activity / timeline hooks。
- Qingxi 10-turn 基本通过。
- 30-turn 不断链。
```

UI 第一阶段任务：

```text
- 新增 docs/playable-ui-design.md。
- 设计三栏布局：Player / Scene+Action / World+Quest+Timeline。
- 前端先服务 Qingxi Demo，不做通用美术。
- 按 play_turn response 直接渲染，不做纯聊天框。
```

完成标准：

```text
前端能：进入 world、看 scene、点 affordance、自由输入、看四层反馈、看 player panel、看 quest/tension、看 npc activity、看 timeline。
```

---

## 8. 推荐执行顺序

```text
1. 提交本验收报告。
2. 更新 docs/master-plan-completion-audit.md v2，对当前 83072b3 重新标注状态。
3. 补 P0 验收测试：raw parse API、bootstrap integrity、candidate history。
4. 补 P1 Beta 2 验收：WorldSpec 批量生成、memory scope contamination。
5. 补 P2 Beta 3 验收：Qingxi 10-turn、30-turn、人工 playtest。
6. 根据验收失败项修机制，不新增外部 Agent/平台。
7. Beta 2/Beta 3 基本通过后，再进入 UI 设计与实现。
```

---

## 9. 当前最终结论

```text
当前项目已经具备 Beta 2 / Beta 3 验收条件，但不能宣布研究报告完成。

已达到：
- 核心机制可验证；
- Fail-forward effect plan 初版；
- ActionTemplate template_only 初版；
- NPC 三层 v0+；
- Drama/Tension/Quest v0+；
- Timeline/Explain 测试雏形。

未达到：
- Beta 2 replay/rebuild/projection 最终验收；
- Beta 3 10-turn / 30-turn 真实可玩验收；
- 多世界生成稳定率；
- UI 产品化体验。

下一步不是继续扩系统，而是执行本报告列出的验收测试和 playtest，并把结果反写到 completion audit。
```
