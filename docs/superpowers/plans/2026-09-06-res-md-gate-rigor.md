# res.md 表述严谨性与 AI 风险提示计划

## 范围

本计划对应分支 `fix-res-md-gate-rigor`，基于 `c6e2232`，不修改 PDF 工具链元数据，不清洗 `Creator`/`Producer`，不改变冻结数值或 AI 使用声明。

## M1–M6 状态

- **M1 已完成**：`backend/app/core/prompts/writer.py` 增加算法复杂度、Pareto 语境、影子价格外推范围、绝对化断言和未实现算法表述约束。
- **M2 已完成**：`backend/app/tools/paper_postprocessor.py` 扩展未实现算法语境豁免，覆盖否定句、比较句和待复算句，避免把排除项误判为当前方法。
- **M3 已完成**：新增算法正确性提示，识别“单纯形法多项式时间”“单目标 Pareto”“完全线性外推”等表述；以 `conditional` 呈现，不替代人工判断。
- **M4 已完成**：将本地套话扫描词表集中为 `AI_BOILERPLATE_TERMS`；仅作可解释的条件提示，不宣称 AI 检测或查重。
- **M5 已完成**：`_check_keywords()` 新增背景实体词与泛化建模词组合检查；关键词数量仍为 3–8，组合风险返回具体 `issues`，按既有 `conditional` 口径处理。当前任务的“生产决策优化”已受控改为“资源优化”。
- **M6 已完成**：Writer 明确附录代码由源码自动生成，禁止直接修改导出后的代码块。

## 验证协议

1. 固定虚拟环境运行 `test_paper_postprocessor`、`test_gate_hardening`、`test_user_output_and_tasks`。
2. 运行 `backend/.venv/Scripts/python.exe -m ruff check app` 与修改模块的 `py_compile`。
3. 对任务 `20260906-033157-bd8195551a4a760570d999c09194c6ab` 执行 `export_cli task-refresh --profile cumcm2026 --local`。
4. 刷新后核对 `preflight`、`pdf_visual`、`submission_audit`、`final_acceptance`、`candidate_manifest` 和五件主产物哈希；`frozen_results.json` 必须保持不变。

## 已知边界

- 关键词组合检查是内部编辑质量提示，不是 CUMCM 官方规则认证；最终是否保留某个领域关键词仍由参赛队员人工判断。
- PDF `Creator`/`Producer` 保留真实导出链指纹；AI 使用声明和支撑材料继续保留。
- `TECHNICAL_PASS` 仍不等于人工完成数学、引用、匿名、排版和提交平台复核。
