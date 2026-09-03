# 硬约束与量纲（0.0.15 提炼，批 D）

**原则**：题面硬约束不可改写为软目标或罚函数；量纲必须一致。

**何时加载**：优化/物理题的 Modeler 阶段（含 LP/非线性/工程优化）。

**执行清单**：
- `constraints` 只写题面/物理硬事实（如 `x_A ≥ 0`、资源上限、几何边界），敏感性扰动范围写 `sensitivity_analysis`，禁止混入。
- 目标与罚项分离：若需罚函数，须在 `method` 中显式声明“原目标 + λ·罚项”，并保留 `original_objective` 与 `penalized_objective` 两个指标。
- 量纲检查：所有 `acceptance_metrics` 的 `unit` 必须与题面单位一致；出现 `unit: 元/小时/件` 时须在 `diagnostic_requirements` 记录量纲核验。

**门禁**：`constraints` 出现敏感性/情景假设即阻断；`acceptance_metrics` 缺 `unit` 或量纲不一致即 FAIL。
