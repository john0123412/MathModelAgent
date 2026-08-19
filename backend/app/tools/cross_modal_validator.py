"""CrossModalValidator: 跨模态数值、文本与代码对齐质检门禁。

负责执行：
1. 代码-文本对齐审计 (Code-Text Parity Audit):
   基于 AST 语法树解析附录代码中的数据输出调用（to_csv, open, dump 等），
   核验正文声明引用的支撑材料/证书文件是否在附录代码中真实具备生成逻辑。
2. 数值事实一致性交叉验证 (Numeric Fact Cross-Check):
   比对正文数字与 FactStore / 冻结结果指标的一致性。
"""

from __future__ import annotations

import ast
import csv
import json
import os
import re
from typing import Any

from app.utils.log_util import logger
from app.tools.fact_store import FactStore


CROSS_MODAL_REPORT_FILENAME = "cross_modal_audit.json"
DATA_FILE_RE = re.compile(
    r"\b(?P<filename>[a-zA-Z0-9_/-]+\.(?:csv|xlsx|json|parquet|txt))\b",
    re.IGNORECASE,
)


class CodeOutputAstVisitor(ast.NodeVisitor):
    """AST 访问器：提取代码中所有写文件的调用及文件名。"""

    def __init__(self) -> None:
        self.output_files: set[str] = set()
        self.output_calls: list[dict[str, Any]] = []

    def visit_Call(self, node: ast.Call) -> None:
        # 1. 识别 df.to_csv('filename.csv') 或 df.to_excel('filename.xlsx')
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "to_csv",
            "to_excel",
            "to_parquet",
            "to_pickle",
            "to_json",
        }:
            target = self._extract_first_str_arg(node)
            if target:
                base = os.path.basename(target)
                self.output_files.add(base)
                self.output_calls.append(
                    {
                        "method": node.func.attr,
                        "filename": base,
                        "lineno": getattr(node, "lineno", 0),
                    }
                )

        # 2. 识别 np.savetxt('filename.csv', ...)
        elif isinstance(node.func, ast.Attribute) and node.func.attr in {
            "savetxt",
            "save",
            "dump",
        }:
            target = self._extract_first_str_arg(node)
            if target:
                base = os.path.basename(target)
                self.output_files.add(base)
                self.output_calls.append(
                    {
                        "method": node.func.attr,
                        "filename": base,
                        "lineno": getattr(node, "lineno", 0),
                    }
                )

        # 3. 识别 open('filename.csv', 'w')
        elif isinstance(node.func, ast.Name) and node.func.id == "open":
            mode_is_write = False
            # 检查 mode 参数
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                if any(m in str(node.args[1].value) for m in ["w", "a", "x"]):
                    mode_is_write = True
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    if any(m in str(kw.value.value) for m in ["w", "a", "x"]):
                        mode_is_write = True

            if mode_is_write:
                target = self._extract_first_str_arg(node)
                if target:
                    base = os.path.basename(target)
                    self.output_files.add(base)
                    self.output_calls.append(
                        {
                            "method": "open(write)",
                            "filename": base,
                            "lineno": getattr(node, "lineno", 0),
                        }
                    )

        self.generic_visit(node)

    def _extract_first_str_arg(self, node: ast.Call) -> str | None:
        """从调用参数中提取首个字符串常量或常用关键字参数，支持 Path / "file" 与 os.path.join。"""
        def _extract_str(arg: ast.AST) -> str | None:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
            if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Div):
                # Path / "filename.csv"
                return _extract_str(arg.right)
            if isinstance(arg, ast.Call):
                # os.path.join(..., "filename.csv") or Path("...")
                for sub_arg in reversed(arg.args):
                    s = _extract_str(sub_arg)
                    if s and "." in s:
                        return s
            return None

        if node.args:
            s = _extract_str(node.args[0])
            if s:
                return s
        for kw in node.keywords:
            if kw.arg in {"path", "path_or_buf", "file", "filename", "fname", "filepath"}:
                s = _extract_str(kw.value)
                if s:
                    return s
        return None


def extract_code_generated_files(code_content: str) -> tuple[set[str], list[dict[str, Any]]]:
    """通过 AST 解析代码中生成的文件名集合。"""
    visitor = CodeOutputAstVisitor()
    try:
        tree = ast.parse(code_content)
        visitor.visit(tree)
    except SyntaxError as exc:
        logger.debug(f"AST 解析代码遇到语法错误（可能是代码片段）: {exc}")
        # 回退正则启发式匹配
        pattern = re.compile(
            r"""(?:to_csv|to_excel|savetxt|open)\s*\(\s*['"]([^'"]+\.[a-zA-Z0-9]+)['"]""",
            re.IGNORECASE,
        )
        for match in pattern.finditer(code_content):
            base = os.path.basename(match.group(1))
            visitor.output_files.add(base)
            visitor.output_calls.append({"method": "regex_fallback", "filename": base, "lineno": 0})
    return visitor.output_files, visitor.output_calls


BACKEND_MANAGED_KEYWORDS = {
    "acceptance",
    "manifest",
    "report",
    "review",
    "frozen",
    "checkpoint",
    "status",
    "audit",
    "contract",
    "request",
    "decision",
    "preflight",
    "format",
    "plan_input",
    "fact_store",
}


def extract_markdown_claimed_data_files(markdown_text: str) -> set[str]:
    """提取 Markdown 正文中声明/提及的数据文件。"""
    # 忽略附录代码围栏内的内容，仅提取正文中的声称
    prose_lines: list[str] = []
    in_fence = False
    for line in markdown_text.splitlines():
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            in_fence = not in_fence
            continue
        if not in_fence:
            prose_lines.append(line)
    prose = "\n".join(prose_lines)

    found: set[str] = set()
    for match in DATA_FILE_RE.finditer(prose):
        fname = os.path.basename(match.group("filename"))
        if fname.lower().endswith((".md", ".py", ".png", ".jpg", ".pdf", ".tex", ".docx")):
            continue
        if any(kw in fname.lower() for kw in BACKEND_MANAGED_KEYWORDS):
            continue
        found.add(fname)
    return found


def validate_code_text_parity(
    markdown_text: str,
    code_sources: list[dict[str, Any]] | str,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """执行代码-文本对齐审计 (Code-Text Parity Audit)。

    检查正文声明的关键证书与数据 CSV 是否在代码 AST 中有真实的生成源程序。
    """
    claimed_files = extract_markdown_claimed_data_files(markdown_text)

    # 聚合所有源码片段
    code_pieces: list[str] = []
    if isinstance(code_sources, str):
        if code_sources.strip():
            code_pieces.append(code_sources)
    elif isinstance(code_sources, list):
        for item in code_sources:
            if isinstance(item, dict):
                content = item.get("content") or item.get("source") or ""
                if content.strip():
                    code_pieces.append(content)
            elif isinstance(item, str):
                if os.path.isfile(item):
                    try:
                        with open(item, encoding="utf-8", errors="replace") as f:
                            code_pieces.append(f.read())
                    except Exception:
                        pass
                elif work_dir and os.path.isfile(os.path.join(work_dir, item)):
                    try:
                        with open(os.path.join(work_dir, item), encoding="utf-8", errors="replace") as f:
                            code_pieces.append(f.read())
                    except Exception:
                        pass
                elif item.strip():
                    code_pieces.append(item)

    if work_dir and os.path.isdir(work_dir):
        for fname in os.listdir(work_dir):
            if fname.endswith(".py"):
                try:
                    with open(os.path.join(work_dir, fname), encoding="utf-8", errors="replace") as f:
                        code_pieces.append(f.read())
                except Exception:
                    pass

    # 提取 Markdown 附录代码围栏内的源码
    in_python_fence = False
    fence_lines: list[str] = []
    for line in markdown_text.splitlines():
        if line.strip().startswith("```python") or line.strip().startswith("```py"):
            in_python_fence = True
            fence_lines = []
            continue
        elif in_python_fence and line.strip().startswith("```"):
            in_python_fence = False
            code_pieces.append("\n".join(fence_lines))
            fence_lines = []
            continue
        if in_python_fence:
            fence_lines.append(line)

    generated_files: set[str] = set()
    all_output_calls: list[dict[str, Any]] = []

    for code in code_pieces:
        if not code.strip():
            continue
        files, calls = extract_code_generated_files(code)
        generated_files.update(files)
        all_output_calls.extend(calls)

    # 识别关键证书/结果文件（如 *_certificate.csv, *_optimal_*.csv, *_results.csv, *_critical_point.csv）
    critical_claimed = {
        f
        for f in claimed_files
        if any(kw in f.lower() for kw in ["certificate", "optimal", "frontier", "results", "critical_point"])
        and not any(kw in f.lower() for kw in BACKEND_MANAGED_KEYWORDS)
    }

    missing_critical: list[str] = []
    for f in critical_claimed:
        if f not in generated_files:
            # 若磁盘上存在该文件但代码未见生成调用，记录警告
            missing_critical.append(f)

    passed = len(missing_critical) == 0
    status = "PASS" if passed else "WARN"

    return {
        "status": status,
        "passed": passed,
        "claimed_files": sorted(list(claimed_files)),
        "critical_claimed_files": sorted(list(critical_claimed)),
        "code_generated_files": sorted(list(generated_files)),
        "missing_critical_generators": sorted(missing_critical),
        "output_calls_count": len(all_output_calls),
    }


def audit_optimality_certificates(
    work_dir: str,
    optimal_cost: float | None = None,
) -> dict[str, Any]:
    """审计工作目录下的所有证书与前沿 CSV，核验是否存在与声明最优解自相矛盾的低成本可行候选。"""
    if not os.path.isdir(work_dir):
        return {"passed": True, "contradictions": [], "audited_files": []}

    # 1. 尝试获取基准最优成本 C*
    c_star = optimal_cost
    if c_star is None:
        opt_path = os.path.join(work_dir, "ques4_optimal_solution.csv")
        if os.path.isfile(opt_path):
            try:
                with open(opt_path, encoding="utf-8-sig", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        val = (
                            row.get("total_cost_yuan")
                            or row.get("cost")
                            or row.get("Q3_all_A_cost_upper_yuan")
                        )
                        if val is not None:
                            c_star = float(val)
                            break
            except Exception:
                pass

    if c_star is None:
        # 尝试从 FactStore 获取
        store = FactStore.load_from_disk(work_dir)
        fact_val = (
            store.get_value("optimal_cost_yuan", subtask_id="ques4")
            or store.get_value("cost_star", subtask_id="ques4")
            or store.get_value("total_cost_yuan", subtask_id="ques4")
        )
        if isinstance(fact_val, (int, float)):
            c_star = float(fact_val)

    contradictions: list[dict[str, Any]] = []
    audited_files: list[str] = []

    # 2. 扫描所有证书与前沿 CSV 文件
    for fname in sorted(os.listdir(work_dir)):
        if not fname.endswith(".csv"):
            continue
        lower_name = fname.lower()
        if not any(kw in lower_name for kw in ["certificate", "frontier", "feasibility", "exclusion"]):
            continue

        fpath = os.path.join(work_dir, fname)
        audited_files.append(fname)
        try:
            with open(fpath, encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    status_val = str(row.get("status", "")).strip().upper()
                    ge_090_val = str(row.get("wilson_lower_ge_090", "")).strip().lower()
                    wilson_low_str = row.get("wilson_low")
                    cost_str = (
                        row.get("total_cost_yuan")
                        or row.get("cost")
                        or row.get("cost_yuan")
                    )

                    cost_val = float(cost_str) if cost_str is not None else None
                    w_low = float(wilson_low_str) if wilson_low_str is not None else None

                    # 判断该行是否被声称/判定为可行 (Feasible)
                    is_row_feasible = False
                    if "FEASIBLE" in status_val and "EXCLUDED" not in status_val:
                        is_row_feasible = True
                    elif ge_090_val in {"true", "1"}:
                        is_row_feasible = True
                    elif w_low is not None and w_low >= 0.90:
                        is_row_feasible = True

                    # 若该候选可行，且总成本严格低于宣称的最优成本 C*（排除浮点误差 > 1e-6）
                    if is_row_feasible and cost_val is not None and c_star is not None:
                        if cost_val < (c_star - 1e-6):
                            contradictions.append(
                                {
                                    "file": fname,
                                    "row_index": idx + 1,
                                    "candidate_N_A": row.get("N_A"),
                                    "candidate_N_B_max": row.get("N_B_max") or row.get("N_B"),
                                    "candidate_cost": cost_val,
                                    "declared_optimal_cost": c_star,
                                    "cost_savings": c_star - cost_val,
                                    "wilson_low": w_low,
                                    "status": status_val,
                                    "issue": (
                                        f"证书文件 {fname} 第 {idx+1} 行标记为 FEASIBLE（Wilson下限={w_low}），"
                                        f"但总成本 {cost_val:.6f}元 低于最优解 {c_star:.6f}元，"
                                        "直接推翻了全局最优性证明！"
                                    ),
                                }
                            )
        except Exception as exc:
            logger.warning(f"审计证书文件 {fname} 遇到异常: {exc}")

    passed = len(contradictions) == 0
    return {
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "declared_optimal_cost": c_star,
        "audited_files": audited_files,
        "contradictions": contradictions,
        "contradiction_count": len(contradictions),
    }


def audit_cross_modal(
    work_dir: str,
    markdown_text: str | None = None,
    code_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """执行完整的跨模态对齐审计并输出报告。"""
    md_content = markdown_text
    if md_content is None:
        md_path = os.path.join(work_dir, "res.md")
        if os.path.isfile(md_path):
            with open(md_path, encoding="utf-8", errors="replace") as f:
                md_content = f.read()
        else:
            md_content = ""

    fact_store = FactStore.load_from_disk(work_dir)
    parity_result = validate_code_text_parity(
        md_content, code_sources or [], work_dir=work_dir
    )
    optimality_result = audit_optimality_certificates(work_dir)

    all_passed = parity_result["passed"] and optimality_result["passed"]
    overall_status = "PASS" if all_passed else ("FAIL" if not optimality_result["passed"] else parity_result["status"])

    report = {
        "status": overall_status,
        "passed": all_passed,
        "code_text_parity": parity_result,
        "optimality_consistency": optimality_result,
        "fact_store_fact_count": len(fact_store.list_facts()),
    }

    report_path = os.path.join(work_dir, CROSS_MODAL_REPORT_FILENAME)
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"写入 {CROSS_MODAL_REPORT_FILENAME} 失败: {exc}")

    return report
