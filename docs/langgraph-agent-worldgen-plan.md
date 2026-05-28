# LangGraph Agent 开发方案：稳定可微调的世界生成

## 1. 目标

在 game-world-kg 项目中，使用 LangGraph 设计一个 **受控 Agent 流程**，确保：
- 世界生成稳定
- 支持分块生成与微调
- 可接受人工干预
- 保持 candidate / canonical 分离
- 可追踪每步生成与修复

---

## 2. 核心 Agent 类型

1. **生成 Agent（WorldGen Candidate Agent）**
   - 负责分块生成 WorldSpec 候选
   - 分块包括 locations / NPC / items / factions / action_templates / tensions / quests
   - 使用 localized JSON repair 修复语法
   - 输出 candidate，不写入 canonical

2. **微调 / 修复 Agent（Candidate Patch Agent）**
   - 修复 Validator 报告的错误
   - 可接受人工修改（新增地点、修改实体属性等）
   - 工具接口包括：get/set JSON path, append/remove path, replace block, validate candidate, get entity registry
   - 循环 validate → patch → validate → adopt / fallback

3. **运行 Agent（Simulation / Drama Manager Agent）**
   - 在游戏运行阶段生成 NPC 行动、动态 tension / quest、事件候选
   - 输出候选事件，由 RuleEngine 决定是否实际执行
   - 不直接写入 EventLog / canonical

---

## 3. LangGraph 架构优势

- 支持节点级状态机和有向图工作流
- 原生支持分支、循环、条件 retry
- 节点级 trace 可追踪 block 生成与修复
- 多 Agent / 工具协作天然适合
- 易于与本地 Validator / JSON Repair / Patch 工具集成

---

## 4. Agent 工作流程

```text
玩家世界想法
→ WorldGen Candidate Agent
    → 分块生成 block candidate
    → 局部 JSON repair
→ Candidate Patch Agent
    → 修复 schema / dangling reference / 人工干预
→ Block merge & consistency check
→ Validator 验证 candidate
→ 循环修复 / fallback
→ Simulation Agent
    → 生成 NPC / tension / quest 候选事件
→ RuleEngine 执行事件
→ World 状态更新
→ Trace 保存全过程
```

---

## 5. 核心原则

- **Candidate 先行**：所有 Agent 都只修改 candidate JSON
- **Canonical 保护**：EventLog / BootstrapCompiler 才是世界真值
- **分块生成**：block-level 独立生成 + 合并
- **微调可控**：Candidate Patch Agent 可接受人工干预
- **追踪完整**：Trace 记录每个 block 生成、修复、merge 情况

---

## 6. Agent 工具接口

- `get_candidate()`  
- `get_validation_report()`  
- `get_entity_registry()`  
- `get_json_path(path)` / `set_json_path(path, value)`  
- `append_json_path(path, value)` / `remove_json_path(path)`  
- `replace_block(block_name, value)`  
- `validate_candidate()`  
- `save_trace_step()`

---

## 7. 修复循环

- 修复 JSON 或 candidate block 错误  
- 每轮循环：
  1. Validator 返回 issue
  2. Agent / Patch Tools 修复 candidate
  3. 再 validate
  4. 最多循环 N 次
  5. 达到上限则 fallback

---

## 8. 与 localized JSON repair 关系

- JSONDecodeError → LocalizedJsonRepairer
- ValidationError / schema issue → Candidate Patch Agent 修复
- 最终 valid → adopt
- Block-level trace 支持调试和回溯

---

## 9. 开发任务建议

1. 新建 LangGraph Agent 节点：WorldGen Candidate Agent
2. 添加 Candidate Patch Agent 节点
3. 构建 block-level merge + consistency 检查
4. 接入 localized JSON repair
5. 添加 Simulation / Drama Manager Agent 节点
6. Trace 系统扩展，记录每个 block 生成、修复、merge、事件候选
7. 测试覆盖：
   - Block-level JSON repair
   - Candidate patch + validation
   - Merge consistency
   - Simulation Agent 输出事件候选
```}