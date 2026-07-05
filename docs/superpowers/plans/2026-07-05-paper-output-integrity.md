# Paper Output Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Writer/Coder 输出与论文后处理在参考文献、问题编号、表格编号上的真实疏漏，使轻量工厂题全链路生成的 CUMCM 论文通过自动预检并减少人工硬伤。

**Architecture:** 在生成端约束 Writer/Coder 不制造裸引用和伪“问题三”，在 `paper_postprocessor` 中做确定性兜底，并让 preflight 显式检查这些硬伤。保持 PDF/DOCX/LaTeX sidecar 导出接口不变，只改变进入导出前的 Markdown 质量门禁。

**Tech Stack:** Python, unittest, ruff, Docker Compose, existing MathModelAgent backend task API.

---

### Task 1: Reference Integrity

**Files:**
- Modify: `backend/app/core/prompts/writer.py`
- Modify: `backend/app/tools/paper_postprocessor.py`
- Test: `backend/app/tests/test_paper_postprocessor.py`

- [x] **Step 1: Write failing reference tests**

Add tests proving `[2]` and `[3]` fail preflight when bibliography only contains `[1]`, and proving the postprocessor removes unsupported inline numeric references while keeping supported `[1]`.

- [x] **Step 2: Implement reference postprocessing**

Add `strip_unmatched_inline_references(markdown) -> tuple[str, list[int]]`, compute bibliography numbers from the reference section, remove only inline numbers that lack corresponding entries, and record removed numbers in `report["fixups"]["removed_unmatched_references"]`.

- [x] **Step 3: Harden writer prompt**

Update the reference protocol so Writer must use full reference payloads or omit numeric marks, and must not hand-write bare `[2]`/`[3]` without entries.

- [x] **Step 4: Verify reference behavior**

Run: `uv run python -m unittest app/tests/test_paper_postprocessor.py`

Expected: tests for missing inline references fail before implementation and pass after implementation.

### Task 2: Extra Problem Label Integrity

**Files:**
- Modify: `backend/app/core/prompts/coder.py`
- Modify: `backend/app/core/prompts/writer.py`
- Modify: `backend/app/core/flows.py`
- Modify: `backend/app/tools/paper_postprocessor.py`
- Test: `backend/app/tests/test_paper_postprocessor.py`

- [x] **Step 1: Write failing label tests**

Add tests proving visible `问题3_...` labels are flagged when `问题重述` declares only two questions, while image paths remain unchanged so exported assets still resolve.

- [x] **Step 2: Implement visible-label normalization**

Add `normalize_extra_problem_labels(markdown, include_code=False) -> tuple[str, int]`, infer declared problem count from the problem restatement, rewrite excess visible labels to `灵敏度分析_...`, and preserve Markdown image target paths.

- [x] **Step 3: Constrain Coder and Writer prompts**

Update Coder output naming rules and sensitivity flow prompts so sensitivity/extension analysis is not treated as a new numbered problem unless the problem statement explicitly has that question.

- [x] **Step 4: Verify label behavior**

Run: `uv run python -m unittest app/tests/test_paper_postprocessor.py`

Expected: visible labels and support-material table entries no longer expose fake `问题3` for a two-question problem.

### Task 3: Table Caption Integrity

**Files:**
- Modify: `backend/app/core/prompts/writer.py`
- Modify: `backend/app/tools/paper_postprocessor.py`
- Test: `backend/app/tests/test_paper_postprocessor.py`

- [x] **Step 1: Write failing table tests**

Add tests proving Markdown tables without preceding `表n` captions fail preflight, and proving the postprocessor inserts captions such as `表1 符号说明` and `表2 支撑材料文件列表`.

- [x] **Step 2: Implement caption insertion and checks**

Add `ensure_table_captions(markdown) -> str`, detect Markdown tables outside fenced code blocks, insert numbered captions from nearby heading/header context, and expose `checks.tables.uncaptioned_tables`.

- [x] **Step 3: Harden writer prompt**

Update Writer format rules so every Markdown table must have an independent numbered title line before the table.

- [x] **Step 4: Verify table behavior**

Run: `uv run python -m unittest app/tests/test_paper_postprocessor.py`

Expected: uncaptained tables fail preflight before postprocessing and pass after caption insertion.

### Task 4: Documentation and Full-Chain Verification

**Files:**
- Modify: `AGENT_MEMORY.md`
- Modify: `STARTUP.md`
- Modify: `docs/md/PDF模板导出说明.md`
- Modify: `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`

- [x] **Step 1: Update handoff and review docs**

Document the new preflight fields: `checks.references.missing_inline`, `checks.tables.uncaptioned_tables`, and `checks.extra_problem_labels.issues`.

- [x] **Step 2: Run local verification**

Run:

```powershell
cd D:\workspace\MathModelAgent\backend
uv run ruff check app
uv run python -m unittest app/tests/test_paper_postprocessor.py app/tests/test_pdf_template_command.py app/tests/test_tex_project_exporter.py app/tests/test_export_profiles.py app/tests/test_user_output_and_tasks.py
```

Expected: ruff exits 0 and unittest reports all tests passing.

- [x] **Step 3: Rebuild Docker and run real task**

Run:

```powershell
cd D:\workspace\MathModelAgent
docker compose up --build -d
curl.exe http://127.0.0.1:8000/docs
```

Then submit the lightweight A/B factory problem through the existing backend task API using the configured environment credentials.

- [x] **Step 4: Validate generated artifacts**

Check the new task work directory:

```text
task completed
paper_preflight_report.json = PASS
export_status.json -> pdf.success = true
pdf_visual_check.json = PASS
candidate_manifest.json registers res.md/res.pdf/res.docx/res.json
tex_export_status.json -> compile_success = true
res.md has no unsupported [2]/[3], has 表n captions, and does not expose fake 问题3 labels for sensitivity analysis
```

### Self-Review

- Spec coverage: P0 reference gaps are covered by Task 1; P1 fake `问题三` labels are covered by Task 2; P2 missing table captions are covered by Task 3; documentation and Docker acceptance are covered by Task 4.
- Placeholder scan: no `TBD`, `TODO`, or vague deferred implementation remains in this plan.
- Type consistency: function names in this plan match the implemented Python API names and test imports.
