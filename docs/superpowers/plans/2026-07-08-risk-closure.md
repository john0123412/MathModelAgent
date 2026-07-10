# Risk-Ordered Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the known incomplete or weak project features in risk order, with one reviewable branch/PR per major task.

**Architecture:** Start with existing endpoints and UI hooks that already exist but do not complete their promised behavior. Keep each task independently testable, avoid broad workflow changes, and defer large new subsystems until small closures are stable.

**Tech Stack:** FastAPI, Python unittest, Vue 3, TypeScript, existing Docker Compose stack.

## Global Constraints

- Work from `D:\workspace\MathModelAgent`.
- Do not run local frontend Node commands on Windows unless explicitly authorized.
- Do not read, print, or persist real API keys, tokens, cookies, or private key material.
- Use one branch and one draft PR per major task.
- Commit after each major task passes its scoped validation.
- For high-risk workflow changes, rebuild Docker and run the project smoke checks until they pass.
- Keep changes minimal and aligned with existing project patterns.

---

## Task 1: Download-All Archive Closure

**Risk:** Low.

**Branch:** `codex/download-all-zip`

**Files:**
- Modify: `backend/app/routers/files_router.py`
- Modify: `frontend/src/apis/filesApi.ts`
- Modify: `frontend/src/pages/task/components/FileSheet.vue`
- Test: `backend/app/tests/test_files_router.py`
- Update docs/memory only if behavior or user-facing instructions change.

**Interfaces:**
- Consumes: existing safe task-id and filename helpers from `app.utils.common_utils`.
- Produces: `GET /download_all_url?task_id=...` creates or refreshes `all.zip` under the task work directory and returns its static URL.

**Steps:**
- [ ] Add tests for archive generation, file inclusion, zip exclusion, missing task handling, and unsafe task-id rejection.
- [ ] Implement safe zip creation in the backend route.
- [ ] Fix frontend `getFiles` response typing to match the backend array response.
- [ ] Expose the existing `downloadAll()` action in the file sheet UI.
- [ ] Run targeted backend tests and `ruff check app`.
- [ ] Commit, push, and open a draft PR.

## Task 2: Token Tracking Endpoint Closure

**Risk:** Low to medium.

**Branch:** `codex/token-track-endpoint`

**Files:**
- Modify: `backend/app/routers/common_router.py`
- Modify: `backend/app/core/llm/llm.py`
- Create or modify: `backend/app/utils/token_usage_recorder.py`
- Test: `backend/app/tests/test_track_endpoint.py`

**Interfaces:**
- Consumes: `StandardResponse.usage`, `agent_name`, `task_id`.
- Produces: `token_usage.json` and `GET /track?task_id=...` response with per-agent usage and totals.

**Steps:**
- [ ] Add tests for missing usage file, malformed usage file, valid aggregation, and unsafe task-id rejection.
- [ ] Add a small recorder used by `LLM.chat()` after successful provider calls.
- [ ] Implement `/track` to read and normalize usage data.
- [ ] Mark costs as estimated and avoid logging secrets.
- [ ] Run targeted backend tests and `ruff check app`.
- [ ] Commit, push, and open a draft PR.

## Task 3: API Config Save Semantics

**Risk:** Medium because it touches API key handling.

**Branch:** `codex/api-config-save-semantics`

**Files:**
- Modify: `backend/app/routers/modeling_router.py`
- Modify: `frontend/src/pages/chat/components/ApiDialog.vue`
- Test: `backend/app/tests/test_api_config.py`

**Interfaces:**
- Consumes: existing `/save-api-config` request shape.
- Produces: explicit response fields indicating `scope: "runtime"` and `persisted: false` unless a later approved persist mode is added.

**Steps:**
- [ ] Add tests proving empty fields do not erase existing config and responses do not echo keys.
- [ ] Return accurate runtime-only save semantics.
- [ ] Update frontend copy so users are not told runtime-only settings were persisted to disk.
- [ ] Do not implement key persistence without a separate explicit approval.
- [ ] Run targeted backend tests and `ruff check app`.
- [ ] Commit, push, and open a draft PR.

## Task 4: Modeling Approval UI Closure

**Risk:** Medium to high because it changes task continuation UX.

**Branch:** `codex/modeling-approval-ui`

**Files:**
- Modify: frontend task API layer.
- Modify: frontend task page/components.
- Add tests only where the current frontend test setup supports it without local Node execution; otherwise verify through Docker/browser.

**Interfaces:**
- Consumes: existing `POST /modeling/{task_id}/approve-modeling`.
- Produces: visible UI path for reviewing and approving a paused modeling decision.

**Steps:**
- [ ] Identify the task status and file signal used when `HUMAN_MODEL_GATE_ENABLED=true`.
- [ ] Add frontend API wrapper for approval.
- [ ] Add task-page action for “确认建模方案并继续”.
- [ ] Verify via Docker/browser when Docker is available.
- [ ] Commit, push, open draft PR, then rebuild Docker and run smoke checks until passing.

## Task 5: Config-Only Feature Guardrails

**Risk:** Medium.

**Branch:** `codex/config-feature-guardrails`

**Files:**
- Modify: settings or startup/status endpoint code.
- Modify: docs/memory as needed.
- Test: backend tests for warning output.

**Interfaces:**
- Consumes: `RAG_ENABLED`, `HIL_ENABLED`, Fallback/Evaluator settings.
- Produces: explicit warnings when config-only features are enabled but not wired into the main workflow.

**Steps:**
- [ ] Add backend warnings/status metadata for config-only features.
- [ ] Ensure warnings are visible without breaking task startup.
- [ ] Update docs/memory if user-facing behavior changes.
- [ ] Run backend tests and `ruff check app`.
- [ ] Commit, push, open draft PR.
