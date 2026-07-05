# AGENT_MEMORY

## 当前稳定状态

- 默认新建建模任务使用 `cumcm2026`。
- 主交付链路是：
  - `res.md`
  - `res.pdf`
  - `res.docx`
  - `res.json`
  - `candidate_manifest.json`
  - `paper_preflight_report.json`
  - `pdf_visual_check.json`
- `latex_project/` 是候选 LaTeX sidecar，不是主交付链路。
- 当前最新真实烟雾任务的主链路曾达到：
  - `paper_preflight_report.json = PASS`
  - `export_status.json -> pdf.success = true`
  - `pdf_visual_check = PASS`
- `cumcm2026` 是基于 2026 修订稿规范实现的暂定模板，不是官方最终 DOCX/LaTeX 模板包。
- 真实提交前仍需人工复核论文内容和 PDF 排版。

## 接手时禁止全盘扫描

- 新 agent 接手时先读 `AGENT_MEMORY.md`。
- 再读 `AGENTS.md`。
- 再按任务需要读指定指南。
- 不要一上来 grep/search 全仓库。
- 不要读取 `.venv/`。
- 不要读取 `frontend/node_modules/`。
- 不要扫描 `backend/project/work_dir/` 下大量历史任务，除非用户明确要求。
- 诊断具体任务时只读对应 `<task_id>` 目录里的报告文件。
- 如果用户没有给 task_id，先按时间列出最近任务目录和报告状态。
- 不要重跑长任务，除非用户明确要求。
- 不要提交、推送、合并，除非用户明确要求。

## 核心文档入口

- `AGENTS.md`
  - 项目级规则、验证方式、前端 Node 限制。
- `STARTUP.md`
  - 启动方式、导出 profile、Docker 验证、CUMCM 2026 状态说明。
- `docs/md/PDF模板导出说明.md`
  - PDF/DOCX/LaTeX 导出说明、字体 fallback、验收要点。
- `docs/md/CUMCM2026模板替换指南.md`
  - 官方模板发布后的快速替换路径。
- `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`
  - preflight/PDF 通过后的人工复核清单。
- `backend/app/templates/export_profiles/README.md`
  - 模板资源目录说明。

## 核心代码入口

- `backend/app/schemas/request.py`
  - `DEFAULT_MODELING_EXPORT_PROFILE = ExportProfile.CUMCM2026`
  - 新建建模任务默认 profile 的源头。
- `backend/app/routers/modeling_router.py`
  - `/modeling` 默认 export profile。
  - 任务创建、取消、续传、建模确认入口。
- `backend/app/tools/export_profiles.py`
  - `CUMCM2026_PROFILE`
  - PDF 变量、DOCX reference、LaTeX sidecar 模板路径。
- `backend/app/tools/pdf_exporter.py`
  - 主 PDF 导出。
  - Pandoc + XeLaTeX。
  - 主 PDF 禁 raw TeX，支持 `$...$` 和 `\(...\)`。
- `backend/app/tools/tex_project_exporter.py`
  - LaTeX sidecar 导出。
  - `latex_project/` 是候选产物。
- `backend/app/tools/paper_postprocessor.py`
  - 参考文献、附录、支撑材料、预检、claim trace。
  - 负责 `paper_preflight_report.json/md`。
- `backend/app/tools/pdf_visual_checker.py`
  - PDF 后验视觉检查。
  - 检查 A4、非空、文本可提取、基础边距风险。
- `backend/app/templates/export_profiles/`
  - DOCX/LaTeX 模板资源。
  - 当前 `cumcm2026` 暂时复用 2025 资源。

## 已知风险

1. LaTeX sidecar 编译失败是非阻断风险；不要把它当成主交付失败。
2. `paper_preflight_report.json = PASS` 不代表数学模型、求解结果、论文论证正确。
3. `cumcm2026` 暂时复用 2025 DOCX reference 和 2025 LaTeX 模板资源；官方 2026 模板发布后按指南替换。
4. 主 PDF 禁 raw TeX；正文应使用 Markdown 表格和标准 `$...$`、`\(...\)` 数学公式。
5. `pdf_visual_check.json = PASS` 只是低成本自动检查，不替代人工翻阅 PDF。
6. Docker 字体会 fallback 到开源字体，正式提交前建议用 Windows 官方字体复核。
7. `candidate_manifest.json` 登记的是候选产物和证据链，不保证论文内容正确。
8. 历史任务目录可能保存旧导出器状态，诊断时要区分“当前代码行为”和“历史产物状态”。

## 失败诊断顺序

- 先看对应任务目录：
  `backend/project/work_dir/<task_id>/`
- 依次读：
  1. `paper_preflight_report.json`
  2. `paper_preflight_report.md`
  3. `export_status.json`
  4. `pdf_visual_check.json`
  5. `tex_export_status.json`
  6. `candidate_manifest.json`
  7. 必要时再看 `res.md`
- 如果 PDF 失败，优先看：
  `export_status.json -> pdf.stderr`
- 如果 preflight FAIL，优先看：
  `paper_preflight_report.json -> checks`
- 如果 PDF 视觉检查失败，优先看：
  `pdf_visual_check.json -> checks`
- 如果 sidecar 失败，先确认是否影响主交付；通常不阻断。
- 如果报告被后续重新导出覆盖，先说明无法从当前文件复原旧 stderr。

## 常用验证命令

```powershell
cd backend
uv run ruff check app
uv run python -m unittest app/tests/test_export_profiles.py app/tests/test_pdf_template_command.py app/tests/test_tex_project_exporter.py app/tests/test_paper_postprocessor.py app/tests/test_user_output_and_tasks.py
uv run python scripts/smoke_pdf_export.py
```

## 常见判断

- 主链路成功通常看：
  - `paper_preflight_report.json = PASS`
  - `export_status.json -> pdf.success = true`
  - `pdf_visual_check.json = PASS`
  - `candidate_manifest.json` 登记主交付文件。
- 如果 `res.pdf` 成功但 `latex_project/` 编译失败，先汇报 sidecar 非阻断。
- 如果 `preflight PASS` 但论文内容可疑，使用最终人工复核清单。
- 如果官方发布 2026 Word/DOCX 模板，按 `docs/md/CUMCM2026模板替换指南.md` 替换 `cumcm2026_docx`。
- 如果官方发布 2026 LaTeX 模板，按 `docs/md/CUMCM2026模板替换指南.md` 新增 `cumcm2026/`。
- 不要覆盖 `cumcm2025/` 或 `cumcm2025_docx/`。
- 如果用户只要求诊断，不要改代码、不要重跑长任务、不要提交。
- 如果用户要求真实烟雾测试，先确认 API key 处理方式，不要在回复里回显 key。
- 如果用户要求前端验证，优先使用 Docker 前端 `http://127.0.0.1:5173`。
- 不要运行本机前端 Node 命令，除非用户明确授权。
- 如果需要看历史任务，先列目录和报告状态，再读取最相关的一个任务。
- 每次声称通过验证前，必须实际运行对应命令。

## 最近相关提交

- `93b02b5 docs: add CUMCM 2026 template replacement guide`
- `dfa89d1 Default modeling exports to cumcm2026`
- `012a68f Fix CUMCM 2026 export validation`

## 沟通口径

- 汇报用中文。
- 不要打印 API key、token、私钥、完整环境变量。
- 未运行验证时必须明确说“未验证”。
- 诊断任务失败时先给结论，再列证据文件和字段。
