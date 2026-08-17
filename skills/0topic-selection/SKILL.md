---
name: 0topic-selection
description: "数学建模竞赛选题路由环节。在 1start-mathmodel 之前调用：对国赛/美赛 A/B/C 等多题横向比较建模路线、工程可行性、验证口径、反驳条件与论文竞争力，并产出可复核的选题评分报告。借鉴开源 skill math-modeling-contest-route-selection 的思路，适配本仓库 9 阶段流水线。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# 选题路由（Topic Selection / Route Comparison）

本 skill 是数学建模工作流的**第 0 阶段**，位于 `1start-mathmodel` 之前。它解决一个你现有流水线没有覆盖的问题：`2analysis-modeling` 默认题已选定、只做单题深做；本 skill 在选题阶段强制横向比较多题（如国赛 A/B/C、美赛 A/B/C/D/E），避免盲选、避免同质化方案。

思路来源：[math-modeling-contest-route-selection](https://github.com/y3519712124-ui/math-modeling-contest-route-selection)（MIT）。本 skill 将该开源 skill 的 `references/` 与 `score_topics.py` 适配到本仓库目录约定下，不重复造轮子。

## 何时调用

- 赛题已发布、用户尚未决定做哪一道时。
- 用户在 `1start-mathmodel` 的偏好询问前，需要先做 A/B/C 横向比较时。

若赛题唯一（如已被指定只做某题），本 skill 可跳过，但应记录“题目唯一，无需横向比较”。

## 必须产出

在当前工作目录创建或更新：

- `reports/TOPIC_SELECTION.md`：各题建模路线比较、可行性、反驳条件、推荐结论。
- `reports/topic_score_report.json` / `reports/topic_score_report.md`：由 `scripts/score_topics.py` 生成的评分排名（若用户已提供结构化评分 JSON）。
- `reports/TOPIC_DECISION.md`：最终选题决定（人工填写或确认）。

## 工作流

### 1. 建立候选集（按题）

为每道可选题目（A/B/C…）建立候选，记录：

- 题目对象、已知数据/附件、决策变量或预测对象。
- 最自然的建模路线（baseline + 1–2 个候选主模型）。
- 工程可行性：数据可得性、参数规模、求解器、代码时间、图表产出。
- 验证口径：用什么小例/留出/量纲/边界行为证明路线可行。
- 反驳条件：什么证据会推翻“该题可做/该路线最优”。

不要以名称相近的算法充数；候选必须在假设、目标、约束或数据需求上有实际差异。

### 2. 逐题建模链设计

把每题的子问题映射为角色：`first`（基线）/ `main`（主模型）/ `extend`（扩展）/ `final`（最终建议）。参考本仓库 `2analysis-modeling` 的子问题拆解口径。

### 3. 模型选择锦标赛（反同质化）

对每题要求写出：

- baseline 是什么、为何不够。
- 被拒绝的方案及理由。
- 主模型及决策测试。
- 翻盘条件（什么情况 fallback）。

惩罚“方法堆叠但无验证”的泛化方案；高级模型只有在改善可测输出、验证或论文叙事时才有价值。

### 4. 工程可行性门控

检查数据、参数、求解器、代码复杂度、图表产出和 fallback 是否支撑该路线；考虑队伍能力与本机环境（见 `AGENTS.md` 资源限制）。

### 5. 评分（可选但推荐）

若已整理好各题评分 JSON，运行：

```bash
python "<0topic-selection skill 目录>/scripts/score_topics.py" input.json -o reports/topic_score_report.md
```

脚本输出总排名、题目层评分、最强建模路线评分、逐问建模链评分，以及缺失字段/同质化风险/fallback 不完整等警告。

`input.json` 字段约定见 `references/selection-rubric.md` 与 `references/paper-scoring-framework.md`。

### 6. 暂停在人工门禁

在 `reports/TOPIC_DECISION.md` 写入推荐结论，状态初始 `PENDING_HUMAN_SELECTION`。只有人工审阅者填写以下全部内容后方可改为 `SELECTED`：

```markdown
## Human decision
- Selected topic: <A/B/C 或题号>
- Reviewer: <name or role>
- Date: <YYYY-MM-DD>
- Rationale: <非空，引用路线比较或评分结论，含假设/风险权衡>
```

`Rationale` 不得为空、不得只写“同意”；没有人工决定时保持阻塞，不得由模型自行选题进入 `1start-mathmodel`。

## 参考文件

本 skill `references/` 直接复用开源 skill 的蒸馏材料（已随本 skill 一并提供或指向 `D:\03_Academic\skills\math-modeling-skills\math-modeling-contest-route-selection\`）：

- `award-method-distillation.md`：国奖论文方法蒸馏。
- `award-question-decomposition.md`：优秀论文逐问分解。
- `award-route-pattern-library.md`：路线模式库。
- `contest-archives.md`：赛题归档。
- `engineering-feasibility.md`：工程可行性。
- `method-map.md`：方法地图。
- `paper-scoring-framework.md`：论文评分框架。
- `problem-taxonomy.md`：问题分类学。
- `refutation-and-model-choice.md`：反驳与模型选择。
- `selection-rubric.md`：选题评分量规。

## 衔接下游

选题确定后，调用 `1start-mathmodel` 进入正式流程；把 `TOPIC_DECISION.md` 的选题结论写入 `plan.md` 的“用户偏好 → 竞赛类型/题目”字段，供 `2analysis-modeling` 作为单题深做的输入。

## 阶段边界

- 本 skill 不写论文正文、不跑完整求解；只做选题决策与路线比较。
- 不替代 `2a-method-validation` 的 PoC+人工门禁；本 skill 的选型是“选哪题/哪条主路线”，`2a` 的选型是“该題内具体方法 PoC 比较”。
