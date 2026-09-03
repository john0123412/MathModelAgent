# Pareto 与加权折中语义（0.0.15 提炼，批 D）

**原则**：Pareto 前沿是支配关系定义的集合，加权求和是单目标标量化，二者不可混称。

**何时加载**：多目标优化题。

**执行清单**：
- 若宣称 Pareto 前沿，必须用非支配检验生成 `pareto_frontier.csv`（含 `dominated` 列），并报告 `pareto_point_count`。
- 加权和只能称“在权重 λ 下的最优折中解”，禁止自动声称“完整 Pareto”。
- `acceptance_metrics` 需分别含 `pareto_point_count`（支配检验）与 `weighted_objective_λ`（标量化），并在 `method` 说明权重选择依据（文献标准/题目原文）。

**门禁**：缺支配检验而声称 Pareto 即 FAIL；`pareto_point_count` 与 CSV 非支配数不一致即 FAIL。
