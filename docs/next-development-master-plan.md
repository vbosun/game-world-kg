# Game-World-KG 开发推进执行级方案

> 本文档严格基于项目研究报告、Beta 2 WorldSpec 小世界生成器方案、Beta 3 Playable Game Layer 方案，以及当前代码进度整理。
>
> 目标不是引入新的外壳方案，而是把 `game-world-kg` 沿研究报告主线推进到：稳定生成、可验证、可运行、可玩 30 分钟。
>
> 本文档暂不把 Agent Patch、LangGraph、PilotDeck、MCP 作为主线任务。它们只能在内核稳定后作为外部工具层考虑。

---

## 0. 核心原则

后续所有开发必须遵守以下原则：

```text
1. SQLite EventLog 是 source of truth。
2. Kuzu 是世界属性图 / 关系查询层，不是真值源。
3. Chroma 是长期记忆 / 证据检索层，不是真值源。
4. LLM 只负责候选生成、叙事、解释、语义解析，不能直接改 canonical。
5. 所有世界变化必须写成 EventRecord。
6. RuleEngine / ActionTemplate 决定合法行动。
7. canonical / player / npc / faction / rumor 必须隔离。
8. NPC 自运行必须经过 RuleEngine，不能直接 set state。
9. Quest 必须来自 Tension，并能追溯 evidence。
10. replay / rebuild / explain 是验收的一部分，不是附加功能。
```

### 禁止事项

```text
- 不允许 WorldSpec 直接写 Kuzu / Chroma 当真值。
- 不允许 LLM 直接写 EventLog 或 canonical state。
- 不允许 NPC Planner 绕过 RuleEngine。
- 不允许 Quest 没有 tension_id / evidence。
- 不允许 ActionTemplate 使用不可执行的自然语言 effect。
- 不允许 Drama Manager 直接修改世界。
- 不允许 Chroma recall 被当成 canonical fact。
- 不允许用“字段存在”冒充“系统完成”。
```

---

## 1. 当前项目状态判断

当前项目已经具备：

```text
- WorldSpec generate / validate / repair / bootstrap API 雏形。
- worldspec_generation_trace 保存雏形。
- Play API：state / scene / affordances / turn / quests / tensions / timeline / npc-tick。
- EventLog / StateProjector / RuleEngine / Affordance / NPCPlanner / Quest / Tension / Explain 基础模块。
- Qingxi / demo worlds seed 雏形。
```

但当前仍存在这些关键差距：

```text
- raw draft / candidate store 仍不够独立明确。
- WorldSpec schema contract 仍可能漂移。
- ActionTemplate runtime 和输入绑定还需继续稳定。
- 成长层目前不能只停留在 skill +1。
- Fail-forward 不能只停留在 ACTION_REJECTED + WITNESS_ATTEMPT。
- NPC 三层调度不能只停留在简单 tick 调用。
- Tension / Quest / Drama 不能只停留在字段增强和 top-N。
- 反馈层必须从扁平 changes 变成四层反馈。
- Beta 3 的 30 分钟可玩 Demo 还需要专门验收。
```

---

## 2. 总体阶段依赖

```text
Phase 1：世界生成稳定化
    ↓
Phase 2：WorldSpec Raw Draft / Candidate 生命周期
    ↓
Phase 3：Bootstrap / Replay / Projection 稳定化
    ↓
Phase 4：ActionTemplate Runtime + 输入绑定稳定化
    ↓
Phase 5：成长层 + Fail-forward
    ↓
Phase 6：NPC 自运行深化
    ↓
Phase 7：Tension / Quest / Drama 深化
    ↓
Phase 8：Beta 3 Playable Game Layer + Qingxi Vertical Slice
```

允许并行：

```text
Phase 5 / Phase 6 / Phase 7 可以在 Phase 4 稳定后并行推进。
Phase 8 必须等待 Phase 5-7 至少有可用版本。
```

---

# Phase 1：世界生成稳定化

## 1.1 目标

让 WorldSpec 生成先稳定，不要求一次完美，但必须做到：

```text
- LLM 原始输出不丢。
- JSON 解析错误可定位。
- schema 错误可操作。
- 常见字段漂移有 prompt / normalizer / validator 三层防线。
```

## 1.2 当前状态

已有：

```text
- /v1/worldspec/generate
- /v1/worldspec/validate
- /v1/worldspec/repair
- /v1/worldspec/debug/latest
- worldspec_generation_trace
```

但仍需注意：

```text
- trace 不等于 raw draft store。
- source_texts 中保存记录不等于 candidate 生命周期。
- 有 JSON repair trace 不等于生成稳定。
```

## 1.3 需要补齐的字段契约

WorldSpec prompt / schema_notes / examples 必须覆盖：

```text
Top-level:
- world_id
- title
- genre
- theme
- starting_area
- scale = small_dense
- player_start.character_id
- player_start.location_id
- background_lore: list[str]

Location:
- id
- stable_key
- name
- description
- connects_to

Character:
- id
- stable_key
- name
- role
- start_location
- goals[].goal_id
- goals[].priority

Item:
- id
- stable_key
- name
- item_type
- owner_id or location_id

Faction:
- id
- stable_key
- name
- faction_type
- goals
- relations[].target 或 target_faction_id
- relations[].relation
- relations[].value 可选

ActionTemplate:
- action_id
- label_template
- target_selector
- arg_schema
- preconditions[] object
- effects[] object
- risk

Tension:
- id
- tension_type
- description
- affected_entities
- evidence
- suggested_actions 可选

Quest:
- id
- title
- issuer_id
- tension_id
- objectives[] object
- evidence
```

## 1.4 需要新增 / 强化的 Validator issue code

```text
worldspec_scale_must_be_small_dense
player_start_missing_location_id
location_missing_stable_key
character_goal_missing_goal_id
character_goal_missing_priority
item_missing_owner_or_location
faction_relation_missing_relation
background_lore_must_be_list
tension_missing_description
tension_missing_evidence
quest_missing_tension_id
quest_objective_must_be_object
action_template_effect_must_be_object
action_template_unsupported_predicate
action_template_unsupported_effect
memory_scope_canonical_contamination
reference_dangling
map_disconnected
small_dense_count_violation
```

## 1.5 开发任务

```text
WG-STABLE-01 补齐 prompt schema notes。
WG-STABLE-02 补齐 WorldSpec 正反例。
WG-STABLE-03 补齐 FactionRelation / CharacterGoal / Tension / QuestObjective examples。
WG-STABLE-04 增强 WorldSpecValidator issue code。
WG-STABLE-05 生成失败时分类 JSONDecodeError / ValidationError / ReferenceError / RuntimeError。
WG-STABLE-06 trace 中保留 raw_text / extracted_json_text / parse_error / validation_report。
```

## 1.6 测试

```text
test_worldspec_prompt_contract_includes_required_fields
test_faction_relation_missing_relation_reports_actionable_issue
test_character_goal_missing_goal_id_reports_actionable_issue
test_background_lore_string_rejected_or_normalized
test_tension_missing_description_reports_actionable_issue
test_invalid_json_still_preserves_raw_response
test_generation_failure_returns_trace_id
```

## 1.7 完成标准

```text
- 坏 JSON 不丢 raw。
- 常见 schema 错误有明确 issue code。
- generate 返回 trace_id。
- debug/latest 能看到 raw / parse_error / validation_report。
- constrained prompt 下 WorldSpec valid rate 明显提升。
```

## 1.8 常见误判

```text
错误：能 fallback sample 就算生成稳定。
正确：fallback 只是兜底，必须保留失败 raw 和明确错误。

错误：Pydantic 报 Field required 就够了。
正确：需要转换成 Agent/人工可理解的 issue code 和 repair_hint。

错误：加了一个正例就算 prompt 完整。
正确：每个高频漂移字段都要有正例/反例/拒绝规则。
```

---

# Phase 2：WorldSpec Raw Draft / Candidate 生命周期

## 2.1 目标

把 WorldSpec 生成结果从“一次性返回值”变成“可保存、可查看、可重新解析、可重复验证、可采纳”的生命周期对象。

## 2.2 必须区分的概念

```text
Raw Draft:
- LLM 原始输出。
- 可能不是合法 JSON。
- 用于调试、人工修复、后续 parse。

Candidate:
- 已经 parse 成 dict / WorldSpec-like JSON。
- 可能 validation 失败。
- 可以重复 validate / repair。

Validated Candidate:
- 通过 WorldSpecValidator。
- 可以进入 bootstrap。

Adopted World:
- 已经通过 BootstrapCompiler 写入 EventLog。
- 成为可运行世界。
```

## 2.3 需要新增的数据结构

建议新增表或等价 repository：

```sql
worldspec_raw_drafts(
  raw_id TEXT PRIMARY KEY,
  trace_id TEXT,
  idea TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  raw_text TEXT NOT NULL,
  extracted_json_text TEXT,
  json_parse_status TEXT,
  json_parse_error TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
)

worldspec_candidates(
  candidate_id TEXT PRIMARY KEY,
  raw_id TEXT,
  trace_id TEXT,
  world_id TEXT,
  spec_json TEXT NOT NULL,
  status TEXT NOT NULL,
  validation_report_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
```

## 2.4 API 建议

```text
GET  /v1/worldspec/raw/latest
GET  /v1/worldspec/raw/{raw_id}
POST /v1/worldspec/raw/{raw_id}/parse

GET  /v1/worldspec/candidates/{candidate_id}
POST /v1/worldspec/candidates/{candidate_id}/validate
POST /v1/worldspec/candidates/{candidate_id}/submit-repaired-json
```

说明：

```text
- submit-repaired-json 第一版可接受人工修好的 JSON。
- 不做 Agent patch。
- 不自动 bootstrap。
```

## 2.5 开发任务

```text
WG-DRAFT-01 新增 raw draft repository。
WG-DRAFT-02 generate_worldspec 中无论成功失败都保存 raw draft。
WG-DRAFT-03 新增 raw/latest 和 raw/{raw_id} API。
WG-DRAFT-04 新增 raw parse API。
WG-DRAFT-05 新增 candidate repository。
WG-DRAFT-06 parse 成功后保存 candidate。
WG-DRAFT-07 candidate validate 可重复执行并更新 validation_report。
WG-DRAFT-08 人工提交 repaired_json_text 后生成新 candidate 或更新 candidate version。
```

## 2.6 测试

```text
test_bad_json_generation_saves_raw_draft
test_raw_latest_returns_last_raw_draft
test_raw_parse_success_creates_candidate
test_raw_parse_failure_preserves_error
test_candidate_validate_updates_report
test_invalid_candidate_cannot_bootstrap
test_submit_repaired_json_creates_validatable_candidate
```

## 2.7 完成标准

```text
- 每次 LLM 生成都有 raw_id。
- JSON 坏了也能在 raw/latest 看到原文。
- raw 可重新 parse。
- candidate 可重复 validate。
- candidate 未 valid 不能 bootstrap。
```

## 2.8 常见误判

```text
错误：source_texts 里有 worldspec_generation_trace 就算 Raw Draft Store。
正确：trace 是过程记录，raw draft 是后续修复对象。

错误：generate 返回 spec 就算 Candidate Store。
正确：candidate 必须有 candidate_id、status、validation_report、可重复 validate。
```

---

# Phase 3：Bootstrap / Replay / Projection 稳定化

## 3.1 目标

让 valid WorldSpec 能可靠变成 EventLog 世界，并且 replay / rebuild 后状态一致。

## 3.2 必须保证的链路

```text
Validated Candidate
→ BootstrapCompiler
→ Bootstrap Event Drafts
→ SQLite transaction
→ EventLog
→ StateProjector
→ KuzuProjector
→ ChromaProjector
→ replay / rebuild consistency
```

## 3.3 Bootstrap 事件顺序

```text
1. WORLD_CREATED
2. CREATE_FACTION
3. CREATE_LOCATION
4. CONNECT_LOCATION
5. CREATE_CHARACTER / CREATE_ENTITY
6. CREATE_ITEM
7. CREATE_RULE
8. CREATE_ACTION_TEMPLATE
9. SET_STATE
10. ADD_MEMORY
11. ADD_TENSION
12. START_QUEST
13. WORLD_BOOTSTRAP_COMPLETED
```

## 3.4 开发任务

```text
BOOT-01 bootstrap 入口只接受 validated candidate 或显式验证通过的 spec。
BOOT-02 bootstrap_runs 记录 world_spec_id / spec_hash / status / event_ids。
BOOT-03 加 idempotency_key，避免重复 bootstrap 同一 spec。
BOOT-04 bootstrap 全流程必须在 SQLite transaction 中完成。
BOOT-05 replay 后 state hash 与当前 state 一致。
BOOT-06 Kuzu rebuild 后基础图查询一致。
BOOT-07 Chroma rebuild 后 background / memory / evidence 可查询。
```

## 3.5 测试

```text
test_invalid_candidate_cannot_bootstrap
test_valid_candidate_bootstrap_writes_world_created
test_bootstrap_is_idempotent_for_same_spec_hash
test_replay_after_bootstrap_matches_state
test_kuzu_rebuild_after_bootstrap_matches_nodes
test_chroma_rebuild_after_bootstrap_recalls_background
test_bootstrap_events_are_in_expected_order
```

## 3.6 完成标准

```text
- valid candidate 能 bootstrap。
- invalid candidate 被拒绝。
- bootstrap 重复请求不会重复写世界。
- replay/rebuild 一致。
- Kuzu/Chroma 均为投影，不参与真值裁决。
```

## 3.7 常见误判

```text
错误：API 能 bootstrap 一次就算完成。
正确：必须验证 idempotency、replay、rebuild。

错误：Kuzu/Chroma 有数据就算完成。
正确：必须证明这些数据可从 EventLog 重建。
```

---

# Phase 4：ActionTemplate Runtime + 输入绑定稳定化

## 4.1 目标

让生成世界中的 ActionTemplate 真正驱动游戏行动，而不是依赖硬编码 demo action。

## 4.2 必须完成的链路

```text
Scene Render
→ AffordanceEngine 根据当前状态生成可行动作
→ 玩家点击按钮或自由输入
→ InputBinder / Intent Parser 绑定到当前 affordance
→ RuleEngine 校验
→ EffectExecutor 执行 effect
→ EventLog 写事件
→ FeedbackRenderer 返回变化
```

## 4.3 ActionTemplate runtime 任务

```text
ACT-01 支持 supported predicates：same_location、has_item、state_equals、state_not_equals、resource_at_least、relation_at_least、connected_location、edge_unblocked、scope_allowed。
ACT-02 支持 supported effects：move_entity、transfer_item、set_state、delta_resource、change_relation、add_memory、add_knowledge、grant_permission、add_identity_tag、add_conversation_event。
ACT-03 ActionTemplateCompiler 检查变量引用：$target、$topic、$item 等必须来自 selector 或 arg_schema。
ACT-04 AffordanceEngine 必须从当前状态和模板推导 3-7 个推荐行动。
ACT-05 硬编码 demo action 不应成为生成世界唯一可玩来源。
```

## 4.4 输入绑定任务

```text
BIND-01 InputBinder 先处理 selected_action_id / selected_target_id。
BIND-02 精确匹配当前 affordance label/action/target。
BIND-03 模糊匹配仅限当前 affordance。
BIND-04 LLM Intent Parser 必须使用 require_current_affordance=True。
BIND-05 如果 LLM 给出 target_id 但不在当前 affordance 中，不能退化到 action_id-only 匹配。
BIND-06 只有 target_id 为空时，才允许 action_id-only fallback。
BIND-07 绑定失败必须返回规则化拒绝和 next_paths。
```

## 4.5 测试

```text
test_affordances_generated_from_worldspec_templates
test_free_input_binds_to_current_affordance
test_selected_action_bypasses_llm_parser
test_llm_parser_cannot_bind_to_non_current_affordance
test_llm_target_mismatch_does_not_fallback_to_wrong_target
test_illegal_free_input_returns_rule_rejection_with_next_paths
test_effect_executor_writes_eventlog
```

## 4.6 完成标准

```text
- 初始场景有 3-7 个可行动作。
- 点击按钮路径稳定。
- 自由输入能绑定常见动作。
- 绑定失败不是“AI 不懂”，而是规则化拒绝。
- 所有合法行动写 EventLog。
```

## 4.7 常见误判

```text
错误：自由输入能偶尔匹配就算完成。
正确：必须保证只绑定当前合法 affordance，不能越权。

错误：有 InputBinder 类就算完成。
正确：必须覆盖 LLM target mismatch、selected action、拒绝反馈等测试。
```

---

# Phase 5：成长层 + Fail-forward

## 5.1 目标

让玩家行动产生长期成长和故事推进，而不是只有 accepted/rejected。

## 5.2 成长层要求

研究报告优先级：

```text
identity     玩家被世界当成什么人
relationship 谁信你、怕你、欠你、怀疑你
knowledge    玩家知道哪些线索、秘密、传闻
permission   玩家能进入哪里、找谁、接什么任务
```

技能和资源可以轻量实现，但不能代替上述四条主成长线。

## 5.3 成长层开发任务

```text
PROG-01 定义 PlayerProgression projection。
PROG-02 支持 ADD_IDENTITY_TAG / REMOVE_IDENTITY_TAG。
PROG-03 支持 ADD_KNOWLEDGE / DISCOVER_CLUE。
PROG-04 支持 GRANT_PERMISSION / REVOKE_PERMISSION。
PROG-05 relationship change 进入 player-visible panel。
PROG-06 skills 做轻量 XP，但不能只有 skill +1。
PROG-07 成长必须能解锁新 affordance。
PROG-08 Quest / scene / feedback 中展示成长结果。
```

## 5.4 Fail-forward 要求

结果模型必须从二元变成：

```text
full_success
success_with_cost
fail_forward
catastrophic_failure
```

失败必须尽量推进局势，例如：

```text
- 被 NPC 目击
- 增加 suspicion
- 消耗资源
- 暴露意图
- 推高 tension
- 解锁一个新线索但付出代价
```

## 5.5 Fail-forward 开发任务

```text
FAIL-01 定义 ActionOutcome model。
FAIL-02 RuleEngine 返回 outcome_type，而不是只有 accepted bool。
FAIL-03 risk action 根据 action.risk、player skill、resource、relation、permission 计算 outcome。
FAIL-04 success_with_cost 生成成本事件。
FAIL-05 fail_forward 生成局势推进事件。
FAIL-06 catastrophic_failure 只用于高风险行动。
FAIL-07 FeedbackRenderer 展示 outcome_type 和代价。
```

## 5.6 测试

```text
test_player_gain_knowledge_unlocks_affordance
test_relationship_gain_unlocks_dialogue_action
test_permission_unlocks_location_access
test_identity_tag_changes_available_actions
test_fail_forward_writes_eventlog
test_success_with_cost_consumes_resource
test_rejected_action_can_create_witness_memory
test_outcome_type_is_returned_in_play_turn
```

## 5.7 完成标准

```text
- 玩家 10 回合内至少获得 knowledge / relation / permission / identity 中的一项。
- 至少一个新 affordance 由成长解锁。
- 失败会产生故事推进，而不是只有拒绝。
- outcome_type 进入 play turn response。
```

## 5.8 常见误判

```text
错误：PLAYER_GROWTH skill +1 就算成长层完成。
正确：必须有 identity / relationship / knowledge / permission，并且影响 affordance。

错误：ACTION_REJECTED + WITNESS_ATTEMPT 就算 Fail-forward 完成。
正确：必须有 outcome_type、风险判定、代价与局势推进。
```

---

# Phase 6：NPC 自运行深化

## 6.1 目标

让世界像小社会，而不是只有玩家行动后几个 NPC 偶尔 tick。

## 6.2 三层 NPC 模拟

```text
Foreground NPC:
- 与玩家同地点 / 同 quest / 同 tension。
- 每回合认真推演 1-3 个。
- 行动进入玩家反馈。

Midground NPC:
- 同区域其他命名 NPC。
- 每 2-4 回合粗粒度推进。
- 可改变位置、关系、传闻。

Background Faction:
- 势力级摘要事件。
- 不深推每个 NPC。
- 只生成可追溯的 faction pressure / rumor / resource shift。
```

## 6.3 开发任务

```text
NPC-01 Foreground selection 基于 same_location / active_quest / active_tension / recent_interaction。
NPC-02 Midground tick 使用低频调度，不应影响每回合性能。
NPC-03 Background faction tick 必须写 SUMMARY_EVENT 或 FACTION_ACTIVITY event，不能只返回内存摘要。
NPC-04 NPCPlanner context 必须包含 goals、memory、rumor、resources、relations、tensions、available_actions。
NPC-05 NPC action 必须经过 RuleEngine。
NPC-06 NPC action 必须可 explain 到 goal/memory/tension。
NPC-07 relationship attributes：trust、suspicion、fear、debt、respect 都要有合理写入规则。
NPC-08 谣言传播必须写 SPREAD_RUMOR / ADD_MEMORY，且 truth_scope=rumor 或 npc，不能污染 canonical。
```

## 6.4 谣言传播规则

```text
- 只有 NPC 知道的 rumor / npc memory 才能传播。
- 传播后进入 listener 的 npc memory 或 rumor scope。
- 不能直接写 canonical。
- 传播需要 evidence_refs 指向源 memory / event。
- 传播概率可由 relationship、location、salience 决定。
```

## 6.5 测试

```text
test_foreground_npc_tick_writes_eventlog
test_midground_tick_runs_every_few_turns
test_background_faction_tick_writes_summary_event
test_npc_action_passes_rule_engine
test_npc_does_not_read_private_player_memory
test_rumor_propagation_keeps_rumor_scope
test_fear_debt_respect_change_from_actions
test_npc_action_explain_contains_goal_memory_or_tension
```

## 6.6 完成标准

```text
- 30 回合内至少 5 次 NPC 主动行动。
- 至少一次 midground 变化。
- 至少一次 background faction summary event。
- 至少一次 rumor propagation。
- fear/debt/respect 至少一个真实影响后续 affordance 或 panel。
```

## 6.7 常见误判

```text
错误：tick_world 返回 background 字段就算背景环完成。
正确：背景环必须写入 EventLog，并能 explain/replay。

错误：SPREAD_RUMOR event 存在就算谣言传播完成。
正确：必须进入 listener memory，scope 正确，且 evidence 可追溯。

错误：字符串 contains 规则写 fear/debt/respect 就算关系系统完成。
正确：关系变化要与 ActionTemplate effect / outcome / NPC goal 关联。
```

---

# Phase 7：Tension / Quest / Drama 深化

## 7.1 目标

让世界矛盾自然生成任务和前台局势。

## 7.2 Tension 模型要求

每条可玩 tension 应尽量包含：

```text
id / tension_id
type / tension_type
reason / description
evidence
affected_entities
suggested_actions
priority
stake
deadline_turn
sponsors
blockers
player_touchpoints
```

## 7.3 Quest 生成要求

Quest 必须：

```text
- 来自 tension。
- 有 tension_id。
- 有 evidence。
- objective 是结构化对象。
- 至少支持一种可执行路径。
- 尽量支持多解法。
- reward / failure consequence 可执行。
```

## 7.4 Drama 1+1+1 要求

Drama foreground 不能只是 top-N。必须输出：

```json
{
  "main_tension": {...},
  "side_tension": {...},
  "ambient_noise": {...},
  "recommended_opportunity": {...},
  "npc_should_approach_player": {...}
}
```

分类建议：

```text
main_tension:
- 与玩家最近行为强相关
- 高 stake / deadline / quest active

side_tension:
- 与世界运行相关，但不压过主线

ambient_noise:
- 环境氛围 / 远处压力 / 背景势力动作
- 不应强行推任务
```

## 7.5 4 层反馈要求

play turn response 中 changes 不应只是扁平 list。建议结构：

```json
{
  "narrative": [
    {"label": "你说服了孙娘", "detail": "..."}
  ],
  "mechanics": [
    {"type": "permission_change", "attr": "enter_backyard", "value": true}
  ],
  "social": [
    {"type": "relationship_change", "npc_id": "sun_niang", "attr": "trust.player", "delta": 1}
  ],
  "world": [
    {"type": "tension_update", "tension_id": "herb_shortage", "delta": -1}
  ]
}
```

## 7.6 开发任务

```text
TQD-01 扩展 Tension dataclass / projection / WorldSpec schema。
TQD-02 TensionScanner 生成 stake/deadline/sponsors/blockers/touchpoints。
TQD-03 QuestGenerator 从任意 tension 生成 structured objectives。
TQD-04 QuestGenerator 支持多 approaches。
TQD-05 QuestValidator 检查 objective / reward / failure consequence 可执行。
TQD-06 DramaManager 输出 main/side/ambient，而不是 scored[:3]。
TQD-07 FeedbackRenderer 输出 narrative/mechanics/social/world 四层。
```

## 7.7 测试

```text
test_tension_contains_playability_fields
test_worldspec_tension_projection_preserves_stake_deadline
test_generic_quest_has_tension_id_and_evidence
test_quest_objectives_are_structured_objects
test_quest_has_multiple_approaches_when_touchpoints_exist
test_drama_foreground_returns_main_side_ambient
test_feedback_changes_are_four_layered
```

## 7.8 完成标准

```text
- 任意 WorldSpec tension 可生成至少一个合理 quest candidate。
- 每个 quest 可追溯 tension/evidence。
- Drama output 明确 1+1+1。
- play turn feedback 输出四层 changes。
```

## 7.9 常见误判

```text
错误：Tension 有 stake 字段就算模型深化完成。
正确：stake/deadline/sponsors/blockers/touchpoints 必须被 Quest/Drama 使用。

错误：Quest 有 alternatives 字段就算多解法。
正确：多解法必须对应不同可执行 affordance / objective path。

错误：Drama 返回 foreground_tensions[:3] 就算 1+1+1。
正确：必须有 main_tension / side_tension / ambient_noise 分类。
```

---

# Phase 8：Beta 3 Playable Game Layer + Qingxi Vertical Slice

## 8.1 目标

证明项目已经从世界模拟器变成可玩的文字沙盒 RPG。

## 8.2 必备 UI / API 面板

```text
Scene Panel:
- 当前地点
- 可见 NPC
- 可见物品
- 地点连接
- 前台 tension

Action Panel:
- 3-7 个推荐行动按钮
- 自由输入框
- 非法输入的规则化拒绝和 next paths

Narrative / Feedback Panel:
- 短叙事
- 四层变化摘要

Player Status Panel:
- identity
- skills
- resources
- knowledge
- permissions

Quest / Tension Panel:
- tension 来源
- 当前目标
- 已知线索
- 可选路线
- 风险 / 奖励

Relationship / Faction Panel:
- trust / fear / debt / suspicion / respect
- faction reputation / hostility / access_level

Rumor / Knowledge Panel:
- 玩家已知线索
- rumor 与 canonical 不混淆

Timeline / Explain Panel:
- 事件链
- 为什么状态变化
- 为什么任务出现
```

## 8.3 Qingxi Town Vertical Slice 要求

前 10 回合体验目标：

```text
1. 玩家知道自己是谁。
2. 玩家知道至少一个短期目标。
3. 玩家认识至少两个 NPC。
4. 玩家获得一条线索或传闻。
5. 玩家触发一次关系变化。
6. 玩家解锁一个新 affordance。
7. NPC 主动行动至少一次。
8. 一条 tension 被前台展示。
9. 任务日志能解释任务来源。
10. 玩家形成 2-3 条可继续路线。
```

30 分钟体验目标：

```text
- 至少 5 次可见世界变化。
- 至少 5 次 NPC active events。
- 至少 1 条因果链可 explain。
- 至少 2 条继续路线。
- 玩家能记住至少 2 个 NPC。
- replay 后状态一致。
- rumor / subjective memory 不污染 canonical。
```

## 8.4 开发任务

```text
PG-01 补齐 play_state 返回所有面板数据。
PG-02 play_turn 返回 scene / affordances / feedback / changes / next_hooks / npc_activity / quests / tensions / relationships。
PG-03 Quest/Tension Journal 产品化。
PG-04 Relationship/Faction/Permission Panel 产品化。
PG-05 Timeline/Explain 产品化。
PG-06 Qingxi WorldSpec / seed 对齐 vertical slice。
PG-07 编写 10 回合 scripted playtest。
PG-08 编写 30 分钟 playability evaluation。
```

## 8.5 测试

```text
test_qingxi_first_goal_within_3_turns
test_qingxi_first_relation_change_within_5_turns
test_qingxi_first_new_affordance_within_8_turns
test_qingxi_has_5_visible_world_changes_in_30min
test_qingxi_has_5_npc_active_events_in_30min
test_qingxi_player_can_explain_one_causal_chain
test_qingxi_replay_consistency
test_qingxi_no_canonical_contamination
```

## 8.6 完成标准

```text
- 玩家可通过 Web UI 或 play API 连续玩 30 分钟。
- 每回合有场景、行动、状态、任务、关系、反馈。
- 自由输入要么绑定合法 ActionTemplate，要么规则化拒绝。
- 10 回合内获得目标和成长反馈。
- NPC 会主动行动。
- Quest Journal 能展示任务来自哪条 tension。
- Relationship/Faction Panel 能显示社会位置变化。
- Explain/Timeline 能解释至少一条因果链。
- replay 后状态一致。
```

## 8.7 常见误判

```text
错误：API 返回很多字段就算可玩。
正确：必须通过 10 回合和 30 分钟 playtest。

错误：有青溪镇 seed 就算 vertical slice。
正确：必须验证前 10 回合目标、成长、NPC、任务、继续路线。

错误：叙事文案好看就算好玩。
正确：每回合必须有结构化世界变化或明确的规则反馈。
```

---

# 9. 近期执行顺序

## P0：纠偏当前实现

```text
P0-01 修复 LLM target mismatch 绑定风险。
P0-02 修复 growth / foreground reaction 另起 turn 污染 timeline 的问题。
P0-03 明确 current implementation status：已完成 / 部分完成 / 未完成。
P0-04 不再用“Phase 1-8 完成”描述当前状态。
```

## P1：补 Phase 1-2

```text
P1-01 Raw Draft Store。
P1-02 Candidate Store。
P1-03 raw/latest / raw/{id} / raw parse API。
P1-04 candidate validate API。
P1-05 prompt contract + validator issue code。
```

## P2：补 Phase 4

```text
P2-01 ActionTemplate runtime 完整测试。
P2-02 InputBinder + LLM binder 安全测试。
P2-03 规则化拒绝体验。
```

## P3：补 Phase 5-7

```text
P3-01 成长层四主线。
P3-02 Fail-forward outcome model。
P3-03 NPC 三层事件化。
P3-04 Tension / Quest 深化。
P3-05 Drama 1+1+1。
P3-06 四层反馈。
```

## P4：Beta 3 竖切

```text
P4-01 Qingxi 10 回合测试。
P4-02 Qingxi 30 分钟测试。
P4-03 Playability metrics。
```

---

# 10. 暂不做内容

在上述内核完成前，暂不推进：

```text
- Agent patch 世界制作器。
- LangGraph 外壳。
- PilotDeck 工作台。
- MCP 对外工具化。
- Unity / Unreal / Godot 客户端。
- 大规模战斗系统。
- 复杂功法树。
- 多人联机。
- 生产级云部署。
```

---

# 11. 最终完成定义

## Beta 2 完成

```text
1. 玩家输入世界想法。
2. 系统生成 WorldSpec。
3. Validator 通过。
4. BootstrapCompiler 编译成事件。
5. SQLite EventLog 写入世界真值。
6. Kuzu 查询到地点、NPC、任务、tension。
7. Chroma 查询到背景和 NPC 初始记忆。
8. 玩家进入世界后有 5 个以上合法可行动作。
9. NPC tick 后世界状态合理变化。
10. 连续运行 30-100 回合。
11. replay / rebuild 后状态一致。
12. canonical 未被 rumor / hallucination 污染。
13. 每个 quest 都能追溯到 tension / evidence。
```

## Beta 3 完成

```text
1. 玩家通过 Web UI 或 play API 进入 WorldSpec 生成的小世界。
2. 每回合看到场景、推荐行动、状态、任务、关系和反馈。
3. 自由输入绑定合法 ActionTemplate 或被规则化拒绝。
4. 10 回合内获得明确目标和至少一个成长反馈。
5. NPC 主动行动，并改变关系、传闻、任务或 tension。
6. Quest Journal 展示任务来源。
7. Relationship/Faction Panel 显示玩家社会位置变化。
8. Explain/Timeline 解释至少一条因果链。
9. Qingxi Town Demo 可连续玩 30 分钟。
10. replay 后状态一致，subjective memory 不污染 canonical。
```
