"""Thin task client for outer Agent to drive Docker backend.

This is the host-side caller defined in roadmap batch B.  It uses a fixed
backend venv and never imports app.config.setting (to avoid accidentally
reading provider credentials).  Normal operations go over HTTP; controlled
candidates go through container CLI (docker compose exec).

Design per docs/superpowers/plans/2026-09-03-agent-docker-backend-roadmap.md §5-6:

- doctor, submit, inspect, events, guide, approve-model, revise-model,
  review-results, resume, cancel, artifacts, repair-code, repair-paper, export

New roadmap contracts (Idempotency-Key, GET /tasks/{id}, events cursor,
artifacts, guidance receipt) are attempted first; missing endpoints degrade
to the existing /tasks, /messages, /files, /download_url family so the client
works before batch B-2 lands.

Usage:
  uv run python -m app.tools.task_client doctor [--base http://127.0.0.1:8000]
  uv run python -m app.tools.task_client submit --ques "题目" --comp CHINA --profile cumcm2026 --file data.xlsx
  uv run python -m app.tools.task_client inspect --task-id 202... --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    import httpx  # type: ignore[import-unresolved]
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    import requests  # type: ignore[import-unresolved]
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

DEFAULT_BASE = os.getenv("MMA_BACKEND_BASE", "http://127.0.0.1:8000")
DEFAULT_TIMEOUT = 15.0
CLIENT_VERSION = "2026-09-03-roadmap-B1"


# ---------------------------------------------------------------------------
# HTTP helpers (httpx preferred, requests fallback, stdlib fallback)
# ---------------------------------------------------------------------------

def _http_get(base: str, path: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    url = f"{base.rstrip('/')}{path}"
    if httpx is not None:
        with httpx.Client(timeout=timeout, follow_redirects=True) as c:
            r = c.get(url, params=params)
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                return {"raw": r.text, "status_code": r.status_code}
    if requests is not None:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"raw": r.text, "status_code": r.status_code}
    # stdlib fallback
    import urllib.request
    import urllib.parse

    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        body = resp.read().decode("utf-8", errors="ignore")
        try:
            return json.loads(body)
        except Exception:
            return {"raw": body, "status_code": resp.status}


def _http_post(
    base: str,
    path: str,
    data: dict | None = None,
    files: dict | None = None,
    form: dict | None = None,
    headers: dict | None = None,
    timeout: float = 300.0,
) -> dict:
    url = f"{base.rstrip('/')}{path}"
    if httpx is not None:
        with httpx.Client(timeout=timeout, follow_redirects=True) as c:
            if files is not None:
                # httpx multipart: files + data
                r = c.post(url, data=form or data, files=files, headers=headers)
            else:
                r = c.post(url, json=data, headers=headers)
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                return {"raw": r.text, "status_code": r.status_code}
    if requests is not None:
        if files is not None:
            r = requests.post(url, data=form, files=files, headers=headers, timeout=timeout)
        else:
            r = requests.post(url, json=data, headers=headers, timeout=timeout)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"raw": r.text, "status_code": r.status_code}
    # stdlib fallback for JSON only
    import urllib.request

    body = json.dumps(data or {}).encode("utf-8") if data is not None else b"{}"
    req = urllib.request.Request(url, data=body, method="POST")  # noqa: S310
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        text = resp.read().decode("utf-8", errors="ignore")
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text, "status_code": resp.status}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_ques(ques: str) -> str:
    return (ques or "").strip()


def _idempotency_key(ques: str, comp_template: str, format_output: str, export_profile: str, file_paths: list[Path]) -> str:
    """Deterministic key from normalized request + file hashes."""
    parts = [
        _normalize_ques(ques),
        comp_template or "",
        format_output or "",
        export_profile or "",
    ]
    for p in sorted(file_paths, key=lambda x: x.name):
        parts.append(f"{p.name}:{_file_sha256(p)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


def _print_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> int:
    """Host connectivity + container capability, no provider probing."""
    base = args.base
    out: dict[str, Any] = {"client_version": CLIENT_VERSION, "base": base, "checks": []}

    # 1. Host -> backend connectivity
    try:
        status = _http_get(base, "/status", timeout=5.0)
        backend_ok = status.get("backend", {}).get("status") == "running"
        redis_ok = status.get("redis", {}).get("status") == "running"
        deployment = status.get("deployment", {})
        out["checks"].append({"name": "host->backend /status", "ok": backend_ok, "detail": status.get("backend")})
        out["checks"].append({"name": "redis", "ok": redis_ok, "detail": status.get("redis")})
        out["checks"].append({"name": "deployment", "ok": True, "detail": deployment})
        code_exec = status.get("code_execution", {})
        ce_ok = code_exec.get("status") == "ready"
        out["checks"].append({"name": "code_execution", "ok": ce_ok, "detail": code_exec})
        out["backend_status"] = status
    except Exception as exc:  # noqa: BLE001
        out["checks"].append({"name": "host->backend /status", "ok": False, "error": str(exc)})
        out["ok"] = False
        _print_json(out)
        return 1

    # 2. Direct 8000 vs 5173 hint
    out["hint"] = "Use --base http://127.0.0.1:8000 for pure backend; /download_url path works without frontend."

    # 3. Capability version check
    try:
        cfg = _http_get(base, "/config", timeout=5.0)
        out["config_deployment"] = cfg.get("deployment")
    except Exception:
        pass

    out["ok"] = all(c.get("ok") for c in out["checks"] if "ok" in c)
    _print_json(out)
    return 0 if out["ok"] else 1


def cmd_submit(args: argparse.Namespace) -> int:
    base = args.base
    ques = args.ques or ""
    if not ques and args.ques_file:
        ques = Path(args.ques_file).read_text(encoding="utf-8")
    ques = _normalize_ques(ques)
    if not ques:
        print("error: --ques or --ques-file required", file=sys.stderr)
        return 2

    file_paths = [Path(p) for p in (args.files or []) if p]
    for p in file_paths:
        if not p.is_file():
            print(f"error: file not found: {p}", file=sys.stderr)
            return 2

    idem_key = args.idempotency_key or _idempotency_key(ques, args.comp_template, args.format_output, args.export_profile, file_paths)

    # multipart form per POST /modeling
    form = {
        "ques_all": ques,
        "comp_template": args.comp_template,
        "format_output": args.format_output,
        "export_profile": args.export_profile,
    }
    if args.require_model_review:
        form["require_model_review"] = "true"
    if args.guidance:
        form["guidance"] = args.guidance

    # Build files for httpx/requests; stdlib fallback not supported for multipart
    if httpx is None and requests is None:
        print("error: httpx or requests required for multipart submit", file=sys.stderr)
        return 2

    files = {}
    opened = []
    try:
        for p in file_paths:
            f = open(p, "rb")  # noqa: SIM115
            opened.append(f)
            # httpx: (filename, fileobj, content_type); requests: (filename, fileobj)
            files[p.name] = (p.name, f, "application/octet-stream") if httpx is not None else (p.name, f)

        # httpx and requests handle files differently; unify via httpx path if available
        headers = {"Idempotency-Key": idem_key}
        if httpx is not None:
            with httpx.Client(timeout=300.0, follow_redirects=True) as c:
                r = c.post(f"{base.rstrip('/')}/modeling", data=form, files=files, headers=headers)
                if r.status_code == 409:
                    # idempotent conflict: same key, different content
                    try:
                        body = r.json()
                    except Exception:
                        body = {"raw": r.text}
                    body["idempotency_key"] = idem_key
                    _print_json(body)
                    return 1
                r.raise_for_status()
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
        else:
            assert requests is not None
            r = requests.post(f"{base.rstrip('/')}/modeling", data=form, files={k: (v[0], v[1]) for k, v in files.items()}, headers=headers, timeout=300)
            if r.status_code == 409:
                try:
                    body = r.json()
                except Exception:
                    body = {"raw": r.text}
                body["idempotency_key"] = idem_key
                _print_json(body)
                return 1
            r.raise_for_status()
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}

        body["idempotency_key"] = idem_key
        # Persist receipt for resume
        receipt_path = Path(args.receipt) if args.receipt else None
        if receipt_path:
            receipt_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_json(body)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"submit failed: {exc}", file=sys.stderr)
        if hasattr(exc, "response"):
            try:
                print(exc.response.text[:2000], file=sys.stderr)  # type: ignore[attr-defined]
            except Exception:
                pass
        return 1
    finally:
        for f in opened:
            try:
                f.close()
            except Exception:
                pass


def cmd_inspect(args: argparse.Namespace) -> int:
    base = args.base
    task_id = args.task_id
    # Prefer new GET /tasks/{id} (roadmap B-2), fallback to GET /tasks list + messages/files
    try:
        data = _http_get(base, f"/tasks/{task_id}", timeout=10.0)
        # New contract returns task_status, workflow_state, revision, allowed_actions, etc.
        _print_json(data)
        return 0
    except Exception as e:  # noqa: BLE001
        # 404 -> fallback
        msg = str(e)
        if "404" not in msg and "Not Found" not in msg:
            # Still try new endpoint error body
            pass
        try:
            tasks = _http_get(base, "/tasks", timeout=10.0)
            task = next((t for t in tasks if isinstance(t, dict) and t.get("task_id") == task_id), None)
            if task is None and isinstance(tasks, dict) and tasks.get("task_id") == task_id:
                task = tasks
            if task is None:
                print(f"task {task_id} not found in /tasks", file=sys.stderr)
                return 1
            # Augment with messages tail and files
            try:
                msgs = _http_get(base, "/messages", params={"task_id": task_id}, timeout=10.0)
                task["messages_tail"] = msgs[-5:] if isinstance(msgs, list) else msgs
            except Exception:
                pass
            try:
                files = _http_get(base, "/files", params={"task_id": task_id}, timeout=10.0)
                task["files"] = files
            except Exception:
                pass
            _print_json(task)
            return 0
        except Exception as exc2:  # noqa: BLE001
            print(f"inspect failed: {exc2} (first: {e})", file=sys.stderr)
            return 1


def cmd_events(args: argparse.Namespace) -> int:
    base = args.base
    task_id = args.task_id
    after = args.after
    limit = args.limit
    # Prefer new cursor endpoint
    try:
        params: dict[str, Any] = {}
        if after is not None:
            params["after"] = after
        if limit is not None:
            params["limit"] = limit
        data = _http_get(base, f"/tasks/{task_id}/events", params=params, timeout=10.0)
        _print_json(data)
        return 0
    except Exception:
        # Fallback: GET /messages and slice
        try:
            msgs = _http_get(base, "/messages", params={"task_id": task_id}, timeout=10.0)
            if not isinstance(msgs, list):
                _print_json(msgs)
                return 0
            # Stable sequence: use list index as cursor
            start = 0
            if after is not None:
                try:
                    start = int(after) + 1
                except ValueError:
                    start = 0
            sliced = msgs[start : start + int(limit or 50)]
            _print_json({"events": sliced, "next_after": start + len(sliced) - 1 if sliced else after, "fallback": True})
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"events failed: {exc}", file=sys.stderr)
            return 1


def cmd_guide(args: argparse.Namespace) -> int:
    base = args.base
    task_id = args.task_id
    role = args.role
    content = args.content or ""
    if not content and args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    payload: dict[str, Any] = {"role": role, "content": content}
    if args.guidance_id:
        payload["guidance_id"] = args.guidance_id
    try:
        data = _http_post(base, f"/modeling/{task_id}/guidance", data=payload, timeout=15.0)
        # New contract returns {guidance_id, status: accepted|consumed}
        _print_json(data)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"guide failed: {exc}", file=sys.stderr)
        return 1


def _simple_post(base: str, task_id: str, action: str, payload: dict | None = None) -> int:
    path = f"/modeling/{task_id}/{action}"
    try:
        data = _http_post(base, path, data=payload or {}, timeout=15.0)
        _print_json(data)
        return 0
    except Exception as exc:  # noqa: BLE001
        # Try to surface structured error with allowed_actions
        msg = str(exc)
        print(f"{action} failed: {msg}", file=sys.stderr)
        # httpx/requests may have response body
        if hasattr(exc, "response"):
            try:
                body = exc.response.json()  # type: ignore[attr-defined]
                _print_json(body)
            except Exception:
                try:
                    print(exc.response.text[:4000], file=sys.stderr)  # type: ignore[attr-defined]
                except Exception:
                    pass
        return 1


def cmd_approve_model(args: argparse.Namespace) -> int:
    return _simple_post(args.base, args.task_id, "approve-modeling")


def cmd_revise_model(args: argparse.Namespace) -> int:
    payload = {"feedback": args.feedback} if args.feedback else {}
    if args.feedback_file:
        payload["feedback"] = Path(args.feedback_file).read_text(encoding="utf-8")
    return _simple_post(args.base, args.task_id, "revise-modeling", payload)


def cmd_review_results(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"action": args.action}
    if args.subtask:
        payload["subtask"] = args.subtask
    if args.review_id:
        payload["review_id"] = args.review_id
    return _simple_post(args.base, args.task_id, "execution-review", payload)


def cmd_resume(args: argparse.Namespace) -> int:
    return _simple_post(args.base, args.task_id, "resume")


def cmd_cancel(args: argparse.Namespace) -> int:
    return _simple_post(args.base, args.task_id, "cancel")


def cmd_artifacts(args: argparse.Namespace) -> int:
    base = args.base
    task_id = args.task_id
    # Prefer new GET /tasks/{id}/artifacts
    try:
        data = _http_get(base, f"/tasks/{task_id}/artifacts", timeout=15.0)
        _print_json(data)
        return 0
    except Exception:
        # Fallback: /files + /download_url stitching
        try:
            files = _http_get(base, "/files", params={"task_id": task_id}, timeout=10.0)
            out = {"task_id": task_id, "files": files, "fallback": True}
            # Try candidate_manifest
            try:
                # No direct HTTP for manifest; would need to fetch via file
                pass
            except Exception:
                pass
            _print_json(out)
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"artifacts failed: {exc}", file=sys.stderr)
            return 1


# ---------------------------------------------------------------------------
# Controlled candidates via docker compose exec (host-side)
# ---------------------------------------------------------------------------

def _compose_exec(backend_cmd: list[str], compose_files: list[str] | None = None) -> tuple[int, str]:
    import subprocess

    root = Path(__file__).resolve().parents[3]
    # Default compose files: docker-compose.yml + local-execution if present
    if compose_files is None:
        compose_files = ["docker-compose.yml"]
        if (root / "docker-compose.local-execution.yml").exists():
            compose_files.append("docker-compose.local-execution.yml")
    args = []
    for f in compose_files:
        args.extend(["-f", f])
    cmd = ["docker", "compose", *args, "exec", "-T", "backend", *backend_cmd]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=120)  # noqa: S603
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def cmd_repair_code(args: argparse.Namespace) -> int:
    code, out = _compose_exec(
        ["uv", "run", "python", "-m", "app.tools.repair_candidate_cli", args.task_id, args.subtask_id, args.review_id, args.candidate, args.evidence]
    )
    print(out)
    return code


def cmd_repair_paper(args: argparse.Namespace) -> int:
    code, out = _compose_exec(
        ["uv", "run", "python", "-m", "app.tools.paper_repair_candidate_cli", args.task_id, args.candidate]
    )
    print(out)
    return code


def cmd_export(args: argparse.Namespace) -> int:
    code, out = _compose_exec(
        ["uv", "run", "python", "-m", "app.tools.export_cli", "task-refresh", "--task-id", args.task_id, "--profile", args.profile]
    )
    print(out)
    return code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # --base is accepted before or after subcommand; use parent parser for reuse
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--base", default=DEFAULT_BASE, help="backend base URL (default: %(default)s or MMA_BACKEND_BASE)")
    p = argparse.ArgumentParser(description="MathModelAgent task client (roadmap B-1)", prog="task_client", parents=[parent])
    p.add_argument("--version", action="version", version=CLIENT_VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("doctor", help="check host->backend, redis, code_execution, deployment")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("submit", help="submit modeling task (idempotent)")
    s.add_argument("--ques", help="problem statement text")
    s.add_argument("--ques-file", help="path to file containing ques_all")
    s.add_argument("--comp", dest="comp_template", default="CHINA", help="comp template (default: CHINA)")
    s.add_argument("--format", dest="format_output", default="Markdown", help="output format")
    s.add_argument("--profile", dest="export_profile", default="cumcm2026", help="export profile")
    s.add_argument("--file", dest="files", action="append", help="attachment file (repeatable)")
    s.add_argument("--require-model-review", action="store_true", help="require_model_review=true")
    s.add_argument("--guidance", help="initial guidance text")
    s.add_argument("--idempotency-key", help="override idempotency key (default: hash of normalized request)")
    s.add_argument("--receipt", help="write response JSON to file for resume")
    s.set_defaults(func=cmd_submit)

    s = sub.add_parser("inspect", help="single task status (prefers GET /tasks/{id})")
    s.add_argument("--task-id", required=True)
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser("events", help="incremental messages (prefers GET /tasks/{id}/events)")
    s.add_argument("--task-id", required=True)
    s.add_argument("--after", help="cursor (last seen seq)")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_events)

    s = sub.add_parser("guide", help="send directed guidance")
    s.add_argument("--task-id", required=True)
    s.add_argument("--role", default="all", choices=["coordinator", "modeler", "coder", "writer", "all"])
    s.add_argument("--content", help="guidance text")
    s.add_argument("--content-file", help="file containing guidance")
    s.add_argument("--guidance-id", help="client-side idempotency for guidance")
    s.set_defaults(func=cmd_guide)

    s = sub.add_parser("approve-model", help="approve modeling plan")
    s.add_argument("--task-id", required=True)
    s.set_defaults(func=cmd_approve_model)

    s = sub.add_parser("revise-model", help="revise modeling plan")
    s.add_argument("--task-id", required=True)
    s.add_argument("--feedback", help="feedback text")
    s.add_argument("--feedback-file", help="file with feedback")
    s.set_defaults(func=cmd_revise_model)

    s = sub.add_parser("review-results", help="execution-review approve/repair")
    s.add_argument("--task-id", required=True)
    s.add_argument("--action", required=True, choices=["approve", "repair"])
    s.add_argument("--subtask", help="subtask id for repair")
    s.add_argument("--review-id", help="review_id binding")
    s.set_defaults(func=cmd_review_results)

    s = sub.add_parser("resume", help="resume interrupted task")
    s.add_argument("--task-id", required=True)
    s.set_defaults(func=cmd_resume)

    s = sub.add_parser("cancel", help="cancel running task")
    s.add_argument("--task-id", required=True)
    s.set_defaults(func=cmd_cancel)

    s = sub.add_parser("artifacts", help="list deliverables (prefers GET /tasks/{id}/artifacts)")
    s.add_argument("--task-id", required=True)
    s.set_defaults(func=cmd_artifacts)

    s = sub.add_parser("repair-code", help="controlled code candidate (docker exec)")
    s.add_argument("--task-id", required=True)
    s.add_argument("--subtask-id", required=True)
    s.add_argument("--review-id", required=True)
    s.add_argument("--candidate", required=True, help="path inside work_dir, e.g. internal/candidate.py")
    s.add_argument("--evidence", required=True, help="evidence json path inside work_dir")
    s.set_defaults(func=cmd_repair_code)

    s = sub.add_parser("repair-paper", help="controlled paper candidate (docker exec)")
    s.add_argument("--task-id", required=True)
    s.add_argument("--candidate", required=True)
    s.set_defaults(func=cmd_repair_paper)

    s = sub.add_parser("export", help="task-refresh export (docker exec)")
    s.add_argument("--task-id", required=True)
    s.add_argument("--profile", default="cumcm2026")
    s.set_defaults(func=cmd_export)

    return p


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Allow --base before or after subcommand: normalize to front
    if "--base" in argv:
        idx = argv.index("--base")
        if idx + 1 < len(argv):
            base_val = argv[idx + 1]
            # Move pair to front if not already at 0
            if idx != 0:
                argv = ["--base", base_val] + [a for i, a in enumerate(argv) if i not in (idx, idx + 1)]
    parser = build_parser()
    args = parser.parse_args(argv)
    # Propagate base
    if not getattr(args, "base", None):
        args.base = DEFAULT_BASE
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
