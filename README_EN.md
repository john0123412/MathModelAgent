<h1 align="center">🤖 MathModelAgent 📐</h1>
<p align="center">
    <img src="./docs/icon.png" height="250px">
</p>
<h4 align="center">
    An agent designed for mathematical modeling<br>
    Automatically complete modeling, code execution, and candidate paper generation; manual review is still required before submission.
</h4>

<h5 align="center"><a href="README.md">简体中文</a> | English</h5>

## 🌟 Vision

Turn 3 days of competition into 1 hour <br>
Automatically generate an award-level modeling paper

<p align="center">
    <img src="./docs/index.png">
    <img src="./docs/chat.png">
    <img src="./docs/coder.png">
    <img src="./docs/writer.png">
</p>

## ✨ Features

- 🔍 Automatic problem analysis, mathematical modeling, code writing, error correction, and paper writing
- 💻 Code Interpreter
    - Cloud Code Interpreter: [E2B](https://e2b.dev/) is the required default; missing `E2B_API_KEY` fails closed instead of falling back
    - Local Interpreter: Jupyter-based and available only with explicit `ALLOW_LOCAL_CODE_EXECUTION=true` in a trusted isolated development environment
- 📝 Generate Markdown / DOCX / PDF / LaTeX sidecar candidate papers and audit reports
- 🤝 Multi-agents: modeling expert, coding expert, paper expert, etc.
- 🔄 Multi-LLMs: Different models for each agent
- 🤖 Built-in OpenAI Chat Completions, OpenAI Responses, Anthropic, and OpenAI-compatible `base_url` configuration; LiteLLM runtime is not integrated
- 💰 Low cost: workflow agentless, no dependency on agent framework
- 🧩 Custom templates: prompt inject for setting requirements for each subtask separately
- 🌐 Literature and web search: Writer `search_papers` aggregates OpenAlex, Semantic Scholar, Crossref, and arXiv; Tavily is only used when `SEARCH_ENABLED=true` and `TAVILY_API_KEY` is configured

## Current Implementation Status (Code Audit: 2026-07-11)

- Implemented: FastAPI/Vue WebUI workflow, default isolated E2B execution, OpenAI/Responses/Anthropic providers, checkpoint resume (including durable early-failure requests and restart interruption recovery), variable snapshots, live user-message injection, multi-source literature search, modeling approval, filtered task archive downloads, aggregate token tracking, CUMCM2026 exports, and submission audits.
- Important CUMCM 2026 boundary: Appendix B writes complete runnable scripts and notebook code cells by default, with coverage and SHA-256 verified through `final_acceptance_report.json -> complete_source_appendix`. The optional `paper_appendix_config.json -> mode=key` intentionally shows excerpts only and cannot receive `TECHNICAL_PASS`. Technical acceptance still does not replace human source execution, mathematical review, or final submission-rule checks.
- Explicit boundaries: `/save-api-config` changes runtime settings only; browser-entered keys are not persisted; task artifacts use controlled downloads; `/track` is best-effort single-process aggregation, not provider billing.
- Not wired into the main workflow: RAG, generic six-action HIL, Fallback Hand Off, Evaluator Shadow Mode, Feedback Rerun, Daytona, LiteLLM runtime, vision models, and R/MATLAB execution.

## 🚀 Current Status and Future Plans

- [x] WebUI workflow: upload task, modeling, code execution, writing, task list, resume.
- [x] Docker deployment configuration.
- [x] Literature search: OpenAlex, Semantic Scholar, Crossref, arXiv, plus optional Tavily web search.
- [x] Checkpoint resume and variable snapshots.
- [x] Markdown, DOCX, PDF, LaTeX sidecar, manifest, preflight, visual check, and submission audit exports.
- [x] E2B cloud interpreter as the default code-execution boundary.
- [ ] Hosted web service operations.
- [ ] Full English/MCM/ICM delivery templates and validation rules.
- [x] Modeling-plan approval through `waiting_review`, frontend approval, and checkpoint resume.
- [ ] Feedback rerun with evaluator scoring.
- [x] Filtered download-all archive generation.
- [x] Best-effort token usage tracking through `/track`.
- [ ] Persistent API configuration.
- [ ] RAG knowledge base.
- [ ] Fallback handoff, shadow evaluator, Daytona, vision models, R/MATLAB, drawing tools, benchmark, chat/agent mode.

## Video Demo

<video src="https://github.com/user-attachments/assets/954cb607-8e7e-45c6-8b15-f85e204a0c5d"></video>

> [!CAUTION]
> The project is in experimental development stage, with many areas needing improvement and optimization. I (the project author) am busy but will update when time permits.
> Contributions are welcome.

For case references, check the [demo](./demo/) folder.
**If you have good cases, please submit a PR to this directory**

## 📖 Usage Guide

Three deployment options are available, choose the one that suits you best:
1. Docker
2. Local deployment
3. Automated script deployment

> If you want to run the CLI version, switch to the [master](https://github.com/jihe520/MathModelAgent/tree/master) branch. It's easier to deploy, but will not be updated in the future.

### 🐳 Option 1: Docker Deployment (Recommended: Simplest)

1. Configure Environment Variables

```bash
cp backend/.env.dev.example backend/.env.dev
cp frontend/.env.example frontend/.env.development
```

Fill in the configuration in:
- backend/.env.dev
- frontend/.env.development

2. Start Services

```bash
docker-compose up -d
```

3. Access

You can now access:
- Frontend interface: http://localhost:5173
- Docker API (recommended via frontend proxy): http://localhost:5173/api
- Direct backend debugging API: http://localhost:8000

Compose binds both ports to `127.0.0.1`; this development deployment must not be exposed directly to the public Internet.

The default Docker mode uses the isolated E2B code sandbox and fails closed when
`E2B_API_KEY` is missing. For a trusted single-user Docker host, use the explicit
local automatic mode when E2B is unavailable:

```powershell
.\scripts\docker-local-execution.ps1 -Action Start
# Resume an existing checkpoint:
.\scripts\docker-local-execution.ps1 -Action Resume -TaskId <task_id>
# Restore the default remote safety mode when finished:
.\scripts\docker-local-execution.ps1 -Action RestoreRemote
```

This mode prefers E2B and falls back to the local interpreter only when explicitly
enabled by the overlay. Do not put `ALLOW_LOCAL_CODE_EXECUTION=true` in the normal
`backend/.env.dev` or use this mode for shared/public deployments.

### 💻 Option 2: Local Deployment

> Make sure Python, Nodejs, and **Redis** are installed on your computer

1. Configure Environment Variables

Copy `/backend/.env.dev.example` to `/backend/.env.dev` (remove the `.example` suffix)

**Configure Environment Variables**

It is recommended to use models with strong capabilities and large parameter counts.

Copy `/frontend/.env.example` to `/frontend/.env.development` (remove the `.example` suffix)

2. Install Dependencies

Clone the project

```bash
git clone https://github.com/jihe520/MathModelAgent.git
```

Start backend

*Start Redis*

```bash
cd backend
pip install uv # Recommended: use uv to manage python projects
uv sync # Install dependencies
# Start backend
# Activate Python virtual environment
source .venv/bin/activate # MacOS or Linux
venv\Scripts\activate.bat # Windows
# Run this command for MacOS or Linux
ENV=DEV uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 120 --reload
# Run this command for Windows
set ENV=DEV ; uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 120
```

Start frontend

```bash
cd frontend
npm install -g pnpm
pnpm i # Make sure pnpm is installed
pnpm run dev
```

[Tutorial](./docs/md/tutorial.md)

Results and outputs are generated in the `backend/project/work_dir/xxx/*` directory:
- notebook.ipynb: code generated during execution
- res.md: final results in markdown format
- res.json: structured result data
- res.docx: Word candidate paper
- res.pdf: PDF candidate paper
- modeler_plan.md / modeler_plan.json: structured modeling plan for review before code execution
- candidate_manifest.json: candidate delivery manifest
- paper_preflight_report.json: paper preflight report
- pdf_visual_check.json: PDF visual check report
- submission_audit_report.json / submission_audit_report.md: pre-submission audit report

The file panel can request a filtered `all.zip`; symlinks, temporary files, existing archives,
internal recovery-candidate PDFs, common cache directories, and oversized inputs are excluded or rejected.

### 🚀 Option 3: Automated Script Deployment (Community Contribution)
Need an automatic deployment script?
[mmaAutoSetupRun](https://github.com/Fitia-UCAS/mmaAutoSetupRun)

Need to customize prompt templates?
Prompt Inject: [prompt](./backend/app/config/md_template.toml)

## 🤝 Contribution & Development

[DeepWiki](https://deepwiki.com/jihe520/MathModelAgent)

- The project is in **experimental development stage** (updated when I have time), with frequent changes and some bugs being fixed.
- Everyone is welcome to participate and make the project better.
- PRs and issues are very welcome.
- For requirements, refer to Future Plans.

After cloning the project, install the **Todo Tree** plugin to view all todo locations in the code.

`.cursor/*` contains overall architecture, rules, and mcp for easier development.

## 📄 License

Free for personal use. For commercial use, please contact me (the author).

[License](./docs/md/License.md)

## 🙏 Reference

Thanks to the following projects:
- [OpenCodeInterpreter](https://github.com/OpenCodeInterpreter/OpenCodeInterpreter/tree/main)
- [TaskWeaver](https://github.com/microsoft/TaskWeaver)
- [Code-Interpreter](https://github.com/MrGreyfun/Local-Code-Interpreter/tree/main)
- [Latex](https://github.com/Veni222987/MathModelingLatexTemplate/tree/main)
- [Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)

## Others

### 💖 Sponsor

[Buy Me a Coffee](./docs/sponser.md)

Thanks to sponsors:
[danmo-tyc](https://github.com/danmo-tyc)

### 👥 GROUP

For questions, join the group

[QQ Group: 699970403](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=rFKquDTSxKcWpEhRgpJD-dPhTtqLwJ9r&authKey=xYKvCFG5My4uYZTbIIoV5MIPQedW7hYzf0%2Fbs4EUZ100UegQWcQ8xEEgTczHsyU6&noverify=0&group_code=699970403)

<div align="center">
    <img src="./docs/qq.jpg" height="400px">
</div>
