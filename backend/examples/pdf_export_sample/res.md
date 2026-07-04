# PDF Export Sample

## 问题重述

某工厂生产 A、B 两种产品。A 需要 2 小时机器时间、1 小时人工时间，利润 40 元；B 需要 1 小时机器时间、2 小时人工时间，利润 30 元。机器时间最多 100 小时，人工时间最多 80 小时。

## 模型建立

设 $x_A$ 和 $x_B$ 分别表示 A、B 两种产品的生产数量，建立线性规划模型：

$$
\max z = 40x_A + 30x_B
$$

约束条件为：

$$
\begin{aligned}
2x_A + x_B &\le 100,\\
x_A + 2x_B &\le 80,\\
x_A, x_B &\ge 0.
\end{aligned}
$$

## 结果说明

该样例用于验证 Markdown 到 PDF 以及 LaTeX sidecar 的导出链路，不代表完整论文。
