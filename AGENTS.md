# MathModelAgent 项目规则

## 前端工具链限制

在 Windows 本机环境中，不要直接运行会调用本地 `frontend/node_modules` 的前端检查或构建命令，包括但不限于：

- `pnpm run build`
- `pnpm exec vue-tsc` / `vue-tsc`
- `pnpm exec vite build` / `vite build`
- `frontend\node_modules\.bin\biome.cmd`
- `pnpm exec biome`

原因：当前环境曾出现这些命令异常派生大量 `node.exe`，导致系统卡死。

如需验证前端，必须先说明风险并获得明确授权；优先采用代码审查、后端单测、Docker 隔离环境或用户手动运行后回传结果。
