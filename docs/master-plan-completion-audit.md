# Game-World-KG Master Plan Completion Audit

> 本文档用于对照 `docs/next-development-master-plan.md` 标注当前 main 分支完成度。
>
> 评估口径：
>
> - **完成**：代码、API、测试或行为已能支撑该条验收。
> - **部分完成 / v0**：结构已接入，但机制深度、测试覆盖或玩法效果不足。
> - **需要测试证明**：代码看起来具备，但缺少针对性验收测试或真实 playtest 证明。
> - **未完成**：当前没有对应实现，或实现与计划目标明显不一致。
>
> 重要原则：字段存在、类存在、提交说明写完成，都不等于系统完成。

---

## 总体结论

当前项目已经进入 **可验证可玩 v0** 阶段，但还不能宣称 `next-development-master-plan.md` 全部完成。

总体状态：

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 1 世界生成稳定化 | 部分完成 | 生成 trace、raw 保存、validator issue 已增强，但 prompt 稳定率仍需实测证明。 |
| Phase 2 Raw Draft / Candidate 生命周期 | 基础完成 | raw/candidate 表、repository、API 已有；invalid schema candidate 生命周期仍可增强。 |
| Phase 3 Bootstrap / Replay / Projection | 部分完成 / 需要测试证明 | bootstrap 基础存在，但 replay/rebuild/idempotency 仍需逐项验收。 |
| Phase 4 ActionTemplate Runtime + 输入绑定 | 基础完成 | target mismatch、绑定越权风险已修；runtime strict 校验和完整覆盖仍需加强。 |
| Phase 5 成长层 + Fail-forward | v0 | 四主线成长开始接入；fail-forward 目前只是 outcome label v0，不是完整 effect plan。 |
| Phase 6 NPC 自运行深化 | v0 | foreground/midground/background 有雏形，background 已事件化；社会模拟深度仍不足。 |
| Phase 7 Tension / Quest / Drama | v0 | rich tension、generic quest、Drama 1+1+1、四层反馈已接入；分类和多解法仍需深化。 |
| Phase 8 Beta 3 Playable Layer | 需要测试证明 | 有 Qingxi 测试雏形，但仍需按 10-turn / 30-turn 验收逐项证明。 |

---

## Phase 1：世界生成稳定化

### 计划要求

`next-development-master-plan.md` 要求 WorldSpec 生成阶段做到：LLM 原始输出不丢、JSON 解析错误可定位、schema 错误可操作、常见字段漂移有 prompt / normalizer / validator 三层防线。

### 当前证据

- `generate_worldspec()` 会写入 `worldspec_generation_trace`，保存 raw response、parse error、validation report、repair attempts、adopted spec 等。
- `generate_worldspec()` 已返回 `trace_id`、`raw_id`、`candidate_id`。
- 新增 `parse_raw_worldspec_text()`，可从保存文本中提取 JSON、`json.loads`、normalize、Pydantic validate。
- Validator 已加入部分更明确的 issue code，例如 faction relation、quest tension、objective object、memory scope 等。

### 状态

**部分完成。**

### 已完成

- 生成 trace 已经存在。
- raw response 不再只停留在 source_texts，已接入 raw draft。
- raw parse 不再重新调用 LLM。
- 常见 schema 问题的 preflight issue 比之前更可操作。

### 未完全完成 / 风险

- Prompt 稳定性还没有用批量生成样本证明。
- “常见字段漂移明显减少”还缺统计指标。
- `parse_raw_worldspec_text()` 目前把 Pydantic validation error 视为 parse failure，不会保存 invalid schema candidate。对人工修复来说，这可能过严。

### 建议补充

- 增加批量 worldgen stability evaluation：同一组 10-20 个 idea，统计 JSON parse success、Pydantic valid、WorldSpecValidator valid、fallback rate。
- 区分 `json_parse_success`、`pydantic_valid`、`worldspec_valid`。
- 对 JSON 可解析但 Pydantic 不通过的 payload，可保存为 `candidate_status=invalid_schema`，便于人工修复。

---

## Phase 2：WorldSpec Raw Draft / Candidate 生命周期

### 计划要求

Raw Draft、Candidate、Validated Candidate、Adopted World 必须分层。Raw Draft 用于保存 LLM 原始输出；Candidate 可重复 validate / repair；Validated Candidate 才能 bootstrap。

### 当前证据

- 新增 `worldspec_raw_drafts` 和 `worldspec_candidates` 表。
- 新增 `RawDraftRepository` 和 `CandidateRepository`。
- 新增 API：
  - `GET /v1/worldspec/raw/latest`
  - `GET /v1/worldspec/raw/{raw_id}`
  - `POST /v1/worldspec/raw/{raw_id}/parse`
  - `GET /v1/worldspec/candidates/{candidate_id}`
  - `POST /v1/worldspec/candidates/{candidate_id}/validate`
  - `POST /v1/worldspec/candidates/{candidate_id}/submit-repaired-json`
- `raw/{raw_id}/parse` 已修复为解析保存的 raw text，不再调用 LLM。

### 状态

**基础完成。**

### 已完成

- Raw Draft Store 已落地。
- Candidate Store 已落地。
- raw latest / get / parse API 已落地。
- candidate get / validate / submit repaired JSON API 已落地。
- generate_worldspec 返回 raw_id / candidate_id。

### 未完全完成 / 风险

- candidate 目前没有版本号、patch history、diff。
- repaired JSON 是覆盖当前 candidate，而不是创建新 version。
- raw parse API 的 endpoint 级测试仍可增强；现有测试主要证明 helper 不调用 LLM。
- Candidate 未 valid 不能 bootstrap 这一点仍需 API/Service 级测试明确证明。

### 建议补充

- 增加 `candidate_versions` 或 `candidate_patch_history`。
- 增加 API 级测试：`test_raw_parse_endpoint_uses_saved_raw_text_not_llm`。
- 增加 `test_invalid_candidate_cannot_bootstrap_from_candidate_endpoint`。

---

## Phase 3：Bootstrap / Replay / Projection 稳定化

### 计划要求

Validated Candidate 应经 BootstrapCompiler 编译成 EventLog，并能 replay / rebuild 一致；Kuzu / Chroma 只能作为投影，不是真值源。

### 当前证据

- `bootstrap_worldspec()` 会 Pydantic validate + WorldSpecValidator validate，通过后保存 spec 并调用 `WorldBootstrapper.bootstrap()`。
- 已有 `world_specs`、`bootstrap_runs` 表。
- Kuzu / Chroma rebuild 相关服务入口已存在。

### 状态

**部分完成 / 需要测试证明。**

### 已完成

- bootstrap 基础链路存在。
- invalid spec 会被 validator 拒绝。
- bootstrap_runs 基础表存在。
- Kuzu / Chroma 作为投影层的服务代码存在。

### 未完全完成 / 风险

- bootstrap idempotency 是否完全符合计划，需要专门测试证明。
- replay 后 state hash 与当前 state 一致，需要自动化测试证明。
- Kuzu rebuild / Chroma rebuild 是否能从 EventLog 完整恢复，需要测试证明。
- `bootstrap-from-file` 仍直接接收 payload，未强制通过 candidate 生命周期；这可以保留为 dev 入口，但不能代表正式 candidate adopt 流程。

### 建议补充

- `test_bootstrap_is_idempotent_for_same_spec_hash`。
- `test_replay_after_bootstrap_matches_state`。
- `test_kuzu_rebuild_after_bootstrap_matches_nodes`。
- `test_chroma_rebuild_after_bootstrap_recalls_background`。

---

## Phase 4：ActionTemplate Runtime + 输入绑定稳定化

### 计划要求

玩家输入必须绑定当前合法 affordance；ActionTemplate runtime 支持 predicates/effects；非法输入要规则化拒绝；所有合法行动写 EventLog。

### 当前证据

- `SUPPORTED_PREDICATES` 已包含基础 predicate，并新增 `has_identity_tag`、`has_permission`、`has_knowledge`。
- `SUPPORTED_EFFECTS` 已包含 `grant_permission`、`add_identity_tag`、`add_knowledge` 等成长相关 effect。
- `_match_affordance()` 已修复：LLM 返回 target_id 时必须精确匹配当前 affordance，不能退化到 action_id-only。
- `ActionTemplateCompiler` 已新增，可检查变量引用。
- `PredicateEvaluator` / `EffectExecutor` 具备基础执行能力。

### 状态

**基础完成。**

### 已完成

- target mismatch 越权绑定风险已修。
- selected action / free input / LLM semantic match 的路径有明确分层。
- 绑定失败会生成 `ACTION_REJECTED` 和可读反馈。
- ActionTemplateCompiler 已存在。

### 未完全完成 / 风险

- `strict=True` 尚未贯通 validator/bootstrap/runtime 的关键路径；未解析变量目前仍可能 warn 后变成空字符串。
- runtime 是否完全摆脱硬编码 demo action，需要继续审查。
- 所有 supported effects 在生成世界里是否都能稳定执行，需要测试覆盖。

### 建议补充

- 在 validator/bootstrap 流程中调用 `ActionTemplateCompiler.compile()`。
- 对 unresolved `$variable` 在 validate 阶段应变成 validation issue，而不是 runtime warning。
- 补齐所有 predicate/effect 的行为测试。

---

## Phase 5：成长层 + Fail-forward

### 计划要求

成长层必须优先支持 identity、relationship、knowledge、permission 四条主线；Fail-forward 必须从二元 accepted/rejected 变成 full_success / success_with_cost / fail_forward / catastrophic_failure，并让失败推进局势。

### 当前证据

- `PLAYER_GROWTH` 事件现在记录 `growth_lines`。
- `_record_growth()` 会扫描 identity / relationship / knowledge / permission / skill。
- `FeedbackRenderer` 已能读取 `growth_lines` 并按成长线生成 change。
- `ActionOutcome` 已定义四类 outcome。
- `validate_and_resolve_action()` 明确注释：当前 outcome 是 v0，effects 执行后才计算 outcome，不是完整 fail-forward effect planning。
- 非 full_success outcome 会进入 feedback。

### 状态

**v0。**

### 已完成

- 成长层不再只是 `skill +1`，四主线已经开始进入 growth_lines。
- feedback 能展示 identity / relationship / knowledge / permission / skill 的成长变化。
- outcome 类型已进入 ActionResolution / FeedbackRenderer。
- 已明确 fail-forward 当前只是 v0 label，避免误判。

### 未完成 / 风险

- 成长解锁 affordance 的系统性验证不足。
- PlayerProgression projection 还不够独立，更多是从 state/payload 汇总。
- Fail-forward 还不是完整机制：目前先执行成功 effects，再计算 outcome。
- success_with_cost / fail_forward / catastrophic_failure 没有对应不同 effect plan。
- 成本、代价、局势推进还没有统一 OutcomeResolver。

### 建议补充

- 增加 `OutcomeResolver`，在 effect execution 前计算 outcome。
- 根据 outcome 选择 `success_effects`、`cost_effects`、`fail_forward_effects`、`catastrophic_effects`。
- 增加成长解锁 affordance 的端到端测试。

---

## Phase 6：NPC 自运行深化

### 计划要求

NPC 应有 foreground / midground / background 三层运行；NPC action 必须经过 RuleEngine / ActionTemplate；谣言传播必须保持 rumor/npc scope；关系属性 trust/fear/debt/respect/suspicion 应真实影响世界。

### 当前证据

- `tick_world()` 已包含 foreground、midground、background 调度。
- NPC action 通过 `validate_and_resolve_action()`，与玩家共享 ActionTemplate validation path。
- `_tick_background()` 已写 `FACTION_ACTIVITY` 到 EventLog，并修复为使用实际 created turn_index。
- `_propagate_rumor()` 已过滤 `truth_scope in {rumor, npc}`。

### 状态

**v0。**

### 已完成

- 三层调度结构存在。
- background 不再只是返回 summary，已经事件化。
- NPC action 不再完全绕过 ActionTemplate path。
- rumor scope guard 已有。

### 未完成 / 风险

- midground 选择逻辑仍偏简单。
- background faction selection 仍偏随机/粗糙。
- NPC 行动是否真正基于 goal/memory/resource/relation/tension，需要 explain 级测试证明。
- fear/debt/respect 的写入和后续 affordance 影响仍需要更多测试。

### 建议补充

- 为 NPC action explain 增加 `goal/memory/tension/relation` evidence。
- 增加 `test_npc_action_explain_contains_goal_memory_or_tension`。
- 增加关系属性影响 affordance 的端到端测试。

---

## Phase 7：Tension / Quest / Drama 深化

### 计划要求

Tension 应包含 stake、deadline、sponsors、blockers、player_touchpoints；Quest 必须来自 tension/evidence，支持多解法；Drama foreground 必须是 1 主线 + 1 副线 + 1 环境噪声；Feedback 必须四层化。

### 当前证据

- Tension 数据结构已扩展 rich fields。
- QuestGenerator 有 generic fallback。
- DramaManager 返回 `main_tension`、`side_tension`、`ambient_noise`，并保留 `foreground_tensions` 兼容字段。
- FeedbackRenderer 返回 flat `changes` 和 `layers`，layers 包含 narrative / mechanics / social / world。

### 状态

**v0。**

### 已完成

- Drama 1+1+1 字段结构已落地。
- 四层反馈结构已落地。
- Growth feedback 已进入四层分类。
- Tension rich fields 已开始被 scoring / opportunity 使用。

### 未完成 / 风险

- Drama main/side/ambient 本质仍主要来自 scored[0]/scored[1]/scored[2:]，分类逻辑不深。
- 多解法 Quest 仍需证明每条 route 对应真实 affordance / objective path。
- stake/deadline/sponsors/blockers/touchpoints 是否贯穿 Quest 和 Drama，需要更多测试证明。

### 建议补充

- 增加 `test_drama_main_side_ambient_are_semantically_distinct`。
- 增加 `test_quest_alternative_routes_map_to_available_affordances`。
- 增加 `test_tension_deadline_changes_drama_priority`。

---

## Phase 8：Beta 3 Playable Game Layer + Qingxi Vertical Slice

### 计划要求

玩家应能通过 Web UI 或 play API 连续玩 30 分钟；10 回合内有目标和成长反馈；NPC 主动行动；Quest Journal 展示任务来源；Relationship/Faction Panel 显示社会位置变化；Explain/Timeline 可解释因果链。

### 当前证据

- Play API 已有 state / scene / affordances / turn / quests / tensions / timeline / npc activity。
- Qingxi 10-turn / 30-turn 测试据最新提交说明已添加。
- player panel、quest journal、tension journal、relationship panel 已有基础。

### 状态

**需要测试证明。**

### 已完成

- Playable API 已具备完整面板雏形。
- 10-turn / 30-turn 自动化测试已开始引入。
- 每回合 response 已包含 scene、affordances、feedback、changes、next_hooks、npc_activity、player、quests、tensions、relationships。

### 未完成 / 风险

- 需要确认 10-turn / 30-turn 测试不是“为测试硬凑 action”，而是覆盖真实可玩路径。
- Web UI 层如果仍薄弱，Beta 3 产品化仍不能算完成。
- Explain/Timeline 是否能解释真实 causal chain，需要端到端验收。

### 建议补充

- `test_qingxi_player_can_explain_one_causal_chain`。
- `test_qingxi_has_two_continuation_paths_after_30_turns`。
- `test_qingxi_no_canonical_contamination_from_rumors`。
- 手动 playtest 记录：至少一次真实 30 分钟游玩日志。

---

# 逐项任务状态表

## Phase 1 Tasks

| Task | 状态 | 说明 |
|---|---|---|
| WG-STABLE-01 prompt schema notes | 部分完成 | 有 schema notes / examples，但稳定率需批量评估。 |
| WG-STABLE-02 WorldSpec 正反例 | 部分完成 | 覆盖了主要结构，仍需持续补高频漂移字段。 |
| WG-STABLE-03 Faction/Goal/Tension/Quest examples | 部分完成 | 已修若干字段，但需看 prompt 文件完整覆盖。 |
| WG-STABLE-04 Validator issue code | 部分完成 | 增强明显，仍可补 repair_hint。 |
| WG-STABLE-05 错误分类 | 部分完成 | raw parse / validation error 有分类，ReferenceError/RuntimeError 仍需更清晰。 |
| WG-STABLE-06 trace 保留 raw/parse/validation | 完成 | trace + raw draft 均已保存。 |

## Phase 2 Tasks

| Task | 状态 | 说明 |
|---|---|---|
| WG-DRAFT-01 raw draft repository | 完成 | `RawDraftRepository` 已有。 |
| WG-DRAFT-02 generate 保存 raw draft | 完成 | generate 返回 raw_id。 |
| WG-DRAFT-03 raw/latest raw/{id} API | 完成 | API 已有。 |
| WG-DRAFT-04 raw parse API | 完成 | 已修为解析保存文本。 |
| WG-DRAFT-05 candidate repository | 完成 | `CandidateRepository` 已有。 |
| WG-DRAFT-06 parse 成功保存 candidate | 完成 | JSON+Pydantic 成功后保存 candidate。 |
| WG-DRAFT-07 candidate validate | 完成 | API 已有。 |
| WG-DRAFT-08 repaired_json | 基础完成 | submit-repaired-json 已有，但无 version/history。 |
| WG-DRAFT-09 批量生成稳定率 | 部分通过 | 10-sample 实测: final valid 100%, LLM parse 50%, fallback 50%。详见 `docs/worldspec-generation-failure-analysis.md`。 |

## Phase 3 Tasks

| Task | 状态 | 说明 |
|---|---|---|
| BOOT-01 bootstrap 只接受 valid | 部分完成 | 直接 payload validate 有，candidate adopt 流程需更明确。 |
| BOOT-02 bootstrap_runs 记录 | 部分完成 | 表存在，需审查 event_ids/status 完整性。 |
| BOOT-03 idempotency | 需要测试证明 | 有 UNIQUE(world_id, spec_hash, status)，但需行为测试。 |
| BOOT-04 transaction | 部分完成 | service bootstrap 使用 transaction，需覆盖异常回滚。 |
| BOOT-05 replay state hash | 未完成 / 需测试 | 未见明确 state hash 验收。 |
| BOOT-06 Kuzu rebuild | 需要测试证明 | rebuild 能力有，验收不足。 |
| BOOT-07 Chroma rebuild | 需要测试证明 | rebuild 能力有，验收不足。 |

## Phase 4 Tasks

| Task | 状态 | 说明 |
|---|---|---|
| ACT-01 predicates | 完成 | 基础 + 成长相关 predicate 已有。 |
| ACT-02 effects | 完成 | 基础 + 成长相关 effect 已有。 |
| ACT-03 compiler | 完成 | `ActionTemplateCompiler` 已有。 |
| ACT-04 3-7 affordances | 需要测试证明 | play_affordances 返回最多 20，是否每场景 3-7 需验收。 |
| ACT-05 减少硬编码 demo action | 部分完成 | ActionTemplateEngine 存在，仍需审查 legacy demo fallback。 |
| BIND-01 selected action | 完成 | InputBinder 路径已有。 |
| BIND-02 精确匹配 | 完成 | target mismatch 已修。 |
| BIND-03 模糊匹配限当前 affordance | 完成 | 需依赖测试覆盖。 |
| BIND-04 LLM require_current_affordance | 完成 | `_llm_bind` 使用该参数。 |
| BIND-05 target mismatch 不 fallback | 完成 | 已修。 |
| BIND-06 无 target 才 fallback | 完成 | 已修。 |
| BIND-07 规则化拒绝 | 完成 | `ACTION_REJECTED` + feedback 已有。 |

## Phase 5 Tasks

| Task | 状态 | 说明 |
|---|---|---|
| PROG-01 PlayerProgression projection | 部分完成 | player_panel + growth_lines 有，独立 projection 仍不足。 |
| PROG-02 identity | v0 | identity growth line 已有。 |
| PROG-03 knowledge | v0 | known_clues / ADD_MEMORY player 已接入。 |
| PROG-04 permission | v0 | permissions 已接入。 |
| PROG-05 relationship panel | v0 | panel 显示关系属性。 |
| PROG-06 skill 轻量 XP | 完成 | skill growth 有。 |
| PROG-07 成长解锁 affordance | 部分完成 / 需测试 | predicate 已有，端到端仍需证明。 |
| PROG-08 成长反馈展示 | 完成 | feedback growth_lines 已修。 |
| FAIL-01 ActionOutcome model | 完成 | enum 已有。 |
| FAIL-02 RuleEngine 返回 outcome | 部分完成 | ActionResolution 有 outcome，完整 RuleEngine 整合需审。 |
| FAIL-03 risk 判定 | v0 | `_compute_outcome` 存在，但后置计算。 |
| FAIL-04 cost events | 未完成 | outcome 未选择 cost effects。 |
| FAIL-05 fail_forward events | 未完成 | outcome 未选择 fail-forward effects。 |
| FAIL-06 catastrophic | v0 | 只有 label。 |
| FAIL-07 Feedback outcome | 完成 | 非 full_success 进入 feedback。 |

## Phase 6 Tasks

| Task | 状态 | 说明 |
|---|---|---|
| NPC-01 foreground selection | v0 | 基于同地点/tension 简单评分。 |
| NPC-02 midground tick | v0 | 每 3 回合粗粒度。 |
| NPC-03 background event | 完成 v0 | `FACTION_ACTIVITY` 写 EventLog，turn_index 已修。 |
| NPC-04 context builder | 部分完成 | 需审查 context 是否含目标/记忆/资源/关系/tension。 |
| NPC-05 RuleEngine path | 基础完成 | 共享 `validate_and_resolve_action`。 |
| NPC-06 explain | 需要测试证明 | 是否可 explain 到 goal/memory/tension 不足。 |
| NPC-07 relation attributes | v0 | 写入/展示有，规则仍粗。 |
| NPC-08 rumor scope | 完成 v0 | scope guard 已有。 |

## Phase 7 Tasks

| Task | 状态 | 说明 |
|---|---|---|
| TQD-01 Tension schema | 完成 v0 | rich fields 已有。 |
| TQD-02 scanner rich fields | 部分完成 | seed/投影有，scanner 泛化需验。 |
| TQD-03 generic quest | v0 | fallback 存在。 |
| TQD-04 multiple approaches | 部分完成 | alternatives 存在，但需映射真实 affordance。 |
| TQD-05 quest validator | 部分完成 | objective/tension 校验有，reward/failure 可执行性不足。 |
| TQD-06 Drama 1+1+1 | 完成 v0 | 字段结构已落地，分类浅。 |
| TQD-07 four-layer feedback | 完成 v0 | layers 已落地。 |

## Phase 8 Tasks

| Task | 状态 | 说明 |
|---|---|---|
| PG-01 play_state 面板 | 部分完成 | 多面板已有。 |
| PG-02 play_turn 完整返回 | 部分完成 | 字段丰富，但可玩性需验证。 |
| PG-03 Quest/Tension Journal | v0 | 有 journal，深度待验。 |
| PG-04 Relationship/Faction/Permission Panel | v0 | relationship/player panel 有，faction/permission 深度待验。 |
| PG-05 Timeline/Explain 产品化 | 部分完成 | explain API 有，产品化和因果链测试不足。 |
| PG-06 Qingxi seed | 部分完成 | seed 有，需对齐竖切目标。 |
| PG-07 10-turn playtest | 需要测试证明 | 测试已开始，但需确认覆盖真实路径。 |
| PG-08 30-min evaluation | 需要测试证明 | 需确认不是形式化通过。 |

---

# 下一步优先级

## P0：不要继续堆功能，先补验收审计测试

1. ✅ API 级 raw parse 测试，证明 endpoint 不调用 LLM。 → `test_raw_parse_endpoint_does_not_call_llm`
2. ✅ Bootstrap replay/rebuild/idempotency 测试。 → `test_bootstrap_is_idempotent_for_same_spec_hash` + `test_replay_after_bootstrap_preserves_state_hash`
3. ✅ 成长解锁 affordance 的端到端测试。 → `test_trust_growth_unlocks_ask_guard_open_gate`
4. ✅ Quest 多解法 route 映射 affordance 测试。 → `test_quest_alternatives_are_current_affordances`
5. ⬜ Qingxi 10-turn / 30-turn 测试覆盖质量审查。 → 已有测试，待质量审查

## P1：把 v0 机制升级到可玩机制

1. Fail-forward 从 label v0 升级为 effect plan。
2. Drama 从 scored index 升级为语义分类。
3. NPC explain 绑定 goal/memory/tension。
4. Candidate repaired-json 增加 version/history。

## P2：产品化体验验证

1. 真实手动 playtest 日志。
2. 30 分钟连续游玩记录。
3. 玩家能否理解成长、局势、任务来源。
4. Explain/Timeline 是否真的能解释“为什么发生”。

---

# 当前可对外表述

推荐表述：

```text
当前项目已进入可验证可玩 v0：
- WorldSpec raw/candidate 生命周期基础完成；
- ActionTemplate runtime 和输入绑定基础稳定；
- 成长、NPC 三层、Drama、四层反馈已经接入 v0；
- 但 Fail-forward 仍是 outcome label v0；
- Beta 2/Beta 3 仍需 replay/rebuild、Qingxi 10-turn/30-turn、Explain 因果链等验收测试证明。
```

不推荐表述：

```text
Phase 1-8 已全部完成。
研究报告已完全完成。
Beta 3 已完成。
Fail-forward 已完成。
```
