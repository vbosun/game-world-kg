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

严格对齐研究报告的详细设计：

- [本体与版本化设计](docs/ontology.md)
- [Event Sourcing 与一致性设计](docs/event-sourcing.md)
- [混合抽取与图谱更新管线](docs/extraction-pipeline.md)
- [评估体系与 PoC 计划](docs/evaluation.md)

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

## 推荐第一个 Demo

先做一个极简城门场景：

```text
地点：村口、铁门、守卫室、内城
人物：玩家、守卫、村长
物品：通行令、银钥匙、钱袋
规则：通行令/钥匙/守卫信任/撬锁影响通行
```

这个场景用于验证位置、物品、关系、记忆、规则、可行动作、状态变化和事件回放。
