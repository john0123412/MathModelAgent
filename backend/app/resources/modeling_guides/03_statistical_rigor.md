# 随机实验与置信区间（0.0.15 提炼，批 D）

**原则**：随机性必须量化，点估计不可作为硬约束判据。

**何时加载**：含 Monte Carlo/Bootstrap/随机优化/抽样的题型。

**执行清单**：
- 所有 Monte Carlo 必须输出 Wilson 95% CI 或 Bootstrap CI，报告 `ci_lower / ci_upper / n_samples`。
- 可行性判据用 `ci_lower ≥ target` 而非点估计 `p̂ ≥ target`。
- 样本量公平：对比方案时近阈值临界点需加密抽样（自适应两阶段），禁止对优解用大样本、对挑战解用小样本。
- `acceptance_metrics` 必须包含 `ci_lower` 与 `n_samples`，且 `description` 含“置信区间/依据/数据统计”三要素。

**门禁**：缺 `ci_lower` 或仅报点估计即阻断；样本量不一致且未说明加密理由即 WARN。
