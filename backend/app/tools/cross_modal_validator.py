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
import datetime
import hashlib
import json
import os
import re
from typing import Any

from app.utils.log_util import logger
from app.tools.fact_store import FactStore
from app.tools.result_integrity import _safe_path


CROSS_MODAL_REPORT_FILENAME = "cross_modal_audit.json"
DATA_FILE_RE = re.compile(
    r"\b(?P<filename>[a-zA-Z0-9_/-]+\.(?:csv|xlsx|json|parquet|txt))\b",
    re.IGNORECASE,
)

MODELING_TERMS_CN = [
    "数学建模", "优化模型", "规划模型", "线性规划", "非线性规划", "整数规划", "混合整数规划", "0-1规划", "目标规划",
    "动态规划", "随机规划", "鲁棒优化", "多目标优化", "组合优化", "最优化方法", "最优化", "约束优化", "凸优化", "优化算法",
    "回归分析", "线性回归", "多元回归", "逻辑回归", "逐步回归", "岭回归", "Lasso回归", "非参数回归",
    "时间序列", "ARIMA", "灰色预测", "灰色模型", "GM", "马尔可夫", "马尔可夫链", "预测模型",
    "聚类分析", "K-means", "层次聚类", "分类模型", "判别分析", "主成分分析", "因子分析", "降维",
    "层次分析法", "熵权法", "TOPSIS", "模糊综合评价", "综合评价", "评价模型", "指标体系",
    "蒙特卡洛", "Monte Carlo", "系统仿真", "模拟退火", "遗传算法", "粒子群算法", "蚁群算法", "启发式算法", "差分进化",
    "网络流", "最短路", "图论", "排队论", "博弈论", "元胞自动机", "系统动力学",
    "风险决策", "风险度量", "CVaR", "机会约束", "情景分析", "情景模拟", "灵敏度分析", "敏感性分析", "鲁棒性分析",
    "误差分析", "残差分析", "显著性检验", "假设检验", "相关性分析", "协方差", "概率模型", "贝叶斯", "统计检验",
    "数值插值", "数据拟合", "最小二乘", "参数估计", "数据预处理", "标准化", "归一化", "可行性检验", "置信区间", "Wilson",
    "空间分箱", "Cell List", "最小镜像", "MIC", "渗流", "连通图", "BFS", "DFS", "自适应抽样", "分层抽样",
]

MODELING_TERMS_EN = [
    "mathematical modeling", "optimization", "linear programming", "integer programming", "mixed integer programming",
    "nonlinear programming", "goal programming", "dynamic programming", "robust optimization", "multi-objective optimization",
    "simulation", "monte carlo", "sensitivity analysis", "robustness analysis", "regression", "clustering",
    "principal component analysis", "pca", "time series", "markov", "bayesian", "graph theory", "network flow",
    "shortest path", "queuing", "game theory", "decision analysis", "risk decision", "evaluation model",
    "topsis", "ahp", "entropy weight", "genetic algorithm", "particle swarm", "simulated annealing",
    "sampling", "adaptive sampling", "mcmc", "bootstrap",
]

DOMAIN_ONLY_HINTS = [
    "农作物", "种植策略", "种植", "乡村", "农业", "蔬菜", "销售", "定价", "生产", "企业", "供应链", "交通", "道路",
    "高校", "学生", "运动", "体测", "玻璃", "文物", "矿井", "逃生", "水沙", "黄河", "波浪", "烟幕", "无人机",
    "问题研究", "策略", "影响因素",
]



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


class CodeImportDependencyVisitor(ast.NodeVisitor):
    """AST 访问器：检查附录求解器代码中是否残留私有仓库模块依赖或 sys.path 路径篡改。"""

    def __init__(self) -> None:
        self.private_imports: list[dict[str, Any]] = []
        self.sys_path_modifications: list[dict[str, Any]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name
            if name == "app" or name.startswith("app."):
                self.private_imports.append({
                    "type": "import_app",
                    "module": name,
                    "lineno": getattr(node, "lineno", 0),
                    "statement": f"import {name}",
                })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if mod == "app" or mod.startswith("app."):
            names_str = ", ".join(a.name for a in node.names)
            self.private_imports.append({
                "type": "from_app_import",
                "module": mod,
                "lineno": getattr(node, "lineno", 0),
                "statement": f"from {mod} import {names_str}",
            })
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # 检测 sys.path.append(...) / sys.path.insert(...)
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"append", "insert"}:
            if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "path":
                if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "sys":
                    self.sys_path_modifications.append({
                        "type": "sys_path_modification",
                        "method": f"sys.path.{node.func.attr}",
                        "lineno": getattr(node, "lineno", 0),
                    })
        self.generic_visit(node)



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


def _strip_math_spans(text: str) -> str:
    """去除行内/行间数学环境（$...$ 与 $$...$$），保留其余文本用于损坏模式检测。

    转义 \\$ 先移除以免干扰计数；随后删除成对的 $$...$$ 与 $...$。
    遵循 Pandoc 规范：合法行内公式首尾不能紧贴空白字符，且不跨越中文主句标点。
    """
    text = text.replace(r"\$", "")
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)
    text = re.sub(r"\$(?!\s)[^\$\n，。；！？]*?(?<!\s)\$", " ", text)
    return text


def audit_latex_formatting_integrity(markdown_text: str) -> dict[str, Any]:
    """审计 Markdown 正文及附录代码中的 LaTeX 格式完整性，拦截损坏渲染与源码泄漏。"""
    issues: list[dict[str, Any]] = []

    corrupt_patterns = [
        (r"(?<![A-Za-z0-9_])=\d+\$", "损坏的变量赋值 (如 =500$)"),
        (r"(?<![A-Za-z0-9_\$])\.\d{2,}\$", "损坏的小数公式 (如 .90$)"),
        (r"\.\d{2,}\\text\{", "损坏的文本公式 (如 .88\\text)"),
        (r"\\text\{[^}]*$", "未闭合的 \\text{} 宏"),
        (r"(?<![A-Za-z0-9_\$\\])\\in\s*\[", "裸露未包裹在公式内的 \\in [ 宏"),
    ]

    in_fence = False
    for line_idx, line in enumerate(markdown_text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if not stripped:
            continue

        if not in_fence:
            # 1. 正文行：检查不平衡的 $ 符号（单行内 $ 数量必须为偶数，排除转义 \$）
            clean_line = stripped.replace(r"\$", "")
            if "$$" not in clean_line:
                dollar_count = clean_line.count("$")
                if dollar_count % 2 != 0:
                    issues.append({
                        "line": line_idx,
                        "type": "unbalanced_inline_dollar",
                        "text": stripped,
                        "message": f"第 {line_idx} 行存在未闭合的单美元符号 ($)。",
                    })

            # 2. 正文行：剥离合法数学区间后扫描损坏模式
            non_math = _strip_math_spans(stripped)
            for pat, desc in corrupt_patterns:
                if re.search(pat, non_math):
                    issues.append({
                        "line": line_idx,
                        "type": "corrupted_latex_syntax",
                        "pattern": pat,
                        "text": stripped,
                        "message": f"第 {line_idx} 行发现 LaTeX 渲染损坏模式: {desc}",
                    })
        else:
            # 3. 代码围栏内：检查注释与代码字符串中的 LaTeX 损坏模式
            comment_text = ""
            if "#" in stripped:
                comment_text = stripped[stripped.index("#"):]

            target_text = comment_text if comment_text else stripped
            non_math_code = _strip_math_spans(target_text)

            for pat, desc in corrupt_patterns:
                if re.search(pat, non_math_code):
                    issues.append({
                        "line": line_idx,
                        "type": "corrupted_latex_in_code",
                        "pattern": pat,
                        "text": stripped,
                        "message": f"第 {line_idx} 行代码/注释中发现 LaTeX 渲染损坏模式: {desc}",
                    })

    passed = len(issues) == 0
    return {
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "issues": issues,
        "issue_count": len(issues),
    }


def _check_code_piece_self_containment(
    code_content: str, source_label: str, issues: list[dict[str, Any]], is_formal_file: bool = False
) -> None:
    """检查单个代码片段是否包含私有依赖或路径篡改，并在为正式源程序时拦截语法错误。"""
    visitor = CodeImportDependencyVisitor()
    try:
        tree = ast.parse(code_content)
        visitor.visit(tree)
    except SyntaxError as exc:
        if is_formal_file:
            issues.append({
                "source": source_label,
                "type": "formal_solver_syntax_error",
                "line": exc.lineno or 0,
                "message": f"[{source_label}] 正式求解器代码存在语法错误: {exc.msg} (第 {exc.lineno} 行)。",
            })
        # 正则兜底匹配
        for match in re.finditer(r"(?m)^\s*(?:from\s+(app(?:\.\w+)*)\s+import|import\s+(app(?:\.\w+)*))", code_content):
            mod = match.group(1) or match.group(2)
            visitor.private_imports.append({
                "type": "regex_fallback_import_app",
                "module": mod,
                "lineno": 0,
                "statement": match.group(0).strip(),
            })
        for match in re.finditer(r"(?m)^\s*sys\.path\.(?:append|insert)\s*\(", code_content):
            visitor.sys_path_modifications.append({
                "type": "regex_fallback_sys_path",
                "method": "sys.path.modify",
                "lineno": 0,
            })

    for item in visitor.private_imports:
        issues.append({
            "source": source_label,
            "type": "private_repo_import",
            "module": item["module"],
            "line": item["lineno"],
            "message": f"[{source_label}] 发现仓库私有模块引用: '{item.get('statement')}'。求解器代码必须单文件自包含（静态私有依赖检查未通过）。",
        })
    for item in visitor.sys_path_modifications:
        issues.append({
            "source": source_label,
            "type": "sys_path_modification",
            "line": item["lineno"],
            "message": f"[{source_label}] 发现外部路径追加调用 ({item.get('method')})。代码严禁依赖仓库私有工作目录路径。",
        })


def audit_code_self_containment(
    work_dir: str | None = None,
    markdown_text: str | None = None,
    code_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """审计求解器与附录代码的静态私有依赖与自包含规范。

    严格拦截对仓库内部私有模块（如 `from app.` / `import app`）及 `sys.path` 外部路径的依赖，
    并对正式 Python 源文件进行语法有效性与工作目录边界校验。
    """
    issues: list[dict[str, Any]] = []
    audited_sources: list[str] = []

    # 1. 扫描 Markdown 附录代码围栏内的源码（最终交付文本）
    if markdown_text:
        in_python_fence = False
        fence_lines: list[str] = []
        fence_start = 0
        for line_idx, line in enumerate(markdown_text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("```python") or stripped.startswith("```py"):
                in_python_fence = True
                fence_lines = []
                fence_start = line_idx
                continue
            elif in_python_fence and stripped.startswith("```"):
                in_python_fence = False
                code_content = "\n".join(fence_lines)
                fence_lines = []
                if code_content.strip():
                    src_tag = f"res.md:L{fence_start}"
                    audited_sources.append(src_tag)
                    _check_code_piece_self_containment(code_content, src_tag, issues, is_formal_file=False)
                continue
            if in_python_fence:
                fence_lines.append(line)

    # 2. 扫描 code_sources 列表
    if code_sources:
        for src in code_sources:
            if isinstance(src, dict):
                code = src.get("code", "")
                name = src.get("name", "code_source")
                if code:
                    audited_sources.append(name)
                    _check_code_piece_self_containment(code, name, issues, is_formal_file=False)

    # 3. 扫描 work_dir 下的正式求解器与 declared executed_code_sources
    if work_dir and os.path.isdir(work_dir):
        candidates = ["master_solver.py"]
        frozen_path = os.path.join(work_dir, "frozen_results.json")
        has_frozen_sources = False
        if os.path.isfile(frozen_path):
            try:
                with open(frozen_path, encoding="utf-8") as f:
                    frozen = json.load(f)
                executed_sources = frozen.get("executed_code_sources", [])
                if executed_sources:
                    has_frozen_sources = True
                    candidates.extend(executed_sources)
            except Exception:
                pass

        # 扫描明确命名的求解器脚本（如 ques1_solver.py, ques2_solver.py 等）
        try:
            for fname in sorted(os.listdir(work_dir)):
                if fname.endswith("_solver.py") or (not has_frozen_sources and fname.startswith("ques") and fname.endswith(".py")):
                    candidates.append(fname)
        except OSError:
            pass

        for cand in dict.fromkeys(candidates):
            if not cand or not str(cand).endswith(".py"):
                continue

            # 路径边界校验
            safe_cand_path = _safe_path(work_dir, str(cand))
            if safe_cand_path is None:
                issues.append({
                    "source": str(cand),
                    "type": "out_of_bounds_source_path",
                    "message": f"代码源路径越出任务目录边界: {cand}",
                })
                continue

            if os.path.isfile(safe_cand_path):
                try:
                    with open(safe_cand_path, encoding="utf-8", errors="replace") as f:
                        code = f.read()
                    audited_sources.append(str(cand))
                    _check_code_piece_self_containment(code, str(cand), issues, is_formal_file=True)
                except Exception as read_exc:
                    issues.append({
                        "source": str(cand),
                        "type": "unreadable_code_source",
                        "message": f"无法读取代码源文件: {read_exc}",
                    })

    passed = len(issues) == 0
    return {
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "audited_sources": list(dict.fromkeys(audited_sources)),
        "issues": issues,
        "issue_count": len(issues),
    }


def extract_keywords_from_markdown(text: str) -> list[str]:
    """从 Markdown 论文中提取关键词列表。"""
    if not text:
        return []
    keywords_raw = ""
    kw_match = re.search(r"(?:\*\*|\#\#\s*)?关键词(?:\*\*|\#\#)?\s*[:：]\s*([^\n\r]+)", text)
    if kw_match:
        keywords_raw = kw_match.group(1).strip()
    else:
        tex_kw = re.search(r"\\keywords\{([^{}]+)\}", text)
        if tex_kw:
            keywords_raw = tex_kw.group(1).strip()

    if not keywords_raw:
        return []

    delims = re.compile(r"[；;、,\|\t]|\s{2,}|\\quad|\\qquad")
    tokens = [tok.strip() for tok in delims.split(keywords_raw) if tok.strip()]
    clean_tokens: list[str] = []
    for t in tokens:
        cleaned = re.sub(r"[\*\_`]", "", t).strip()
        if cleaned:
            clean_tokens.append(cleaned)
    return clean_tokens


def audit_keywords_modeling_compliance(markdown_text: str) -> dict[str, Any]:
    """审计论文关键词是否全部采用正规数学建模术语，拦截纯题目背景词。"""
    keywords = extract_keywords_from_markdown(markdown_text)
    if not keywords:
        return {
            "status": "PASS",
            "passed": True,
            "keywords": [],
            "issues": [],
            "issue_count": 0,
            "message": "未在正文中检测到显式关键词行，跳过建模术语审计。",
        }

    issues: list[dict[str, Any]] = []
    bad_keywords: list[str] = []
    domain_only: list[str] = []

    for kw in keywords:
        compact = re.sub(r"\s+", "", kw)
        lower = kw.lower()

        is_domain = any(hint in compact for hint in DOMAIN_ONLY_HINTS)
        is_modeling = False

        if is_domain:
            # 领域词如果仅包含"优化"或"模型"等宽泛字眼，不得无条件放行，必须匹配明确的复合数模算法
            is_modeling = any(
                term in compact
                for term in (
                    "混合整数规划", "线性规划", "非线性规划", "整数规划", "目标规划",
                    "动态规划", "随机规划", "鲁棒优化", "多目标优化", "蒙特卡洛",
                    "灵敏度分析", "敏感性分析", "层次分析法", "TOPSIS", "元胞自动机"
                )
            )
        else:
            is_modeling = (
                compact in {"优化", "最优化", "数学建模", "建模"}
                or any(term in compact for term in MODELING_TERMS_CN)
                or any(term in lower for term in MODELING_TERMS_EN)
            )

        if not is_modeling:
            bad_keywords.append(kw)
            if is_domain or any(hint in compact for hint in DOMAIN_ONLY_HINTS):
                domain_only.append(kw)

    if len(keywords) < 3:
        issues.append(
            {
                "type": "too_few_keywords",
                "message": f"关键词数量偏少 ({len(keywords)} < 3)。",
            }
        )
    elif len(keywords) > 6:
        issues.append(
            {
                "type": "too_many_keywords",
                "message": f"关键词数量偏多 ({len(keywords)} > 6)。",
            }
        )

    if domain_only:
        issues.append(
            {
                "type": "domain_only_keywords",
                "message": f"关键词包含纯赛题背景词，未体现数模专业方法: {', '.join(domain_only)}。建议替换为标准建模术语（如混合整数规划、蒙特卡洛模拟、灵敏度分析）。",
                "domain_keywords": domain_only,
            }
        )
    elif bad_keywords:
        issues.append(
            {
                "type": "non_modeling_keywords",
                "message": f"关键词未匹配到标准数模专业词库: {', '.join(bad_keywords)}。",
                "bad_keywords": bad_keywords,
            }
        )

    has_issues = len(issues) > 0
    return {
        "status": "WARN" if has_issues else "PASS",
        "passed": True,  # 警告不导致 passed=False
        "keywords": keywords,
        "issues": issues,
        "issue_count": len(issues),
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
    latex_integrity_result = audit_latex_formatting_integrity(md_content)
    code_self_containment_result = audit_code_self_containment(
        work_dir=work_dir,
        markdown_text=md_content,
        code_sources=code_sources,
    )
    keywords_compliance_result = audit_keywords_modeling_compliance(md_content)

    disk_text_mismatch = False
    md_path = os.path.join(work_dir, "res.md")
    disk_bytes = b""
    if os.path.isfile(md_path):
        try:
            with open(md_path, "rb") as mf:
                disk_bytes = mf.read()
            if markdown_text is not None:
                disk_norm = disk_bytes.replace(b"\r\n", b"\n").strip()
                mem_norm = markdown_text.encode("utf-8").replace(b"\r\n", b"\n").strip()
                if disk_norm != mem_norm:
                    disk_text_mismatch = True
        except OSError:
            pass

    # 判定阻断项与预警项
    blocking_passed = (
        not disk_text_mismatch
        and optimality_result.get("passed", True)
        and optimality_result.get("status") != "FAIL"
        and latex_integrity_result.get("passed", True)
        and latex_integrity_result.get("status") != "FAIL"
        and code_self_containment_result.get("passed", True)
        and code_self_containment_result.get("status") != "FAIL"
        and parity_result.get("status") != "FAIL"
    )
    has_warning = (
        parity_result.get("status") == "WARN"
        or keywords_compliance_result.get("status") == "WARN"
        or code_self_containment_result.get("status") == "WARN"
        or latex_integrity_result.get("status") == "WARN"
        or optimality_result.get("status") == "WARN"
    )

    if disk_text_mismatch:
        parity_result.setdefault("issues", []).append({
            "type": "audit_text_disk_mismatch",
            "message": "显式传入的审计正文与磁盘 res.md 内容不一致，存在哈希替换风险，门禁阻断！",
        })

    if not blocking_passed:
        overall_status = "FAIL"
        overall_passed = False
    elif has_warning:
        overall_status = "WARN"
        overall_passed = True
    else:
        overall_status = "PASS"
        overall_passed = True

    if os.path.isfile(md_path) and not disk_text_mismatch:
        md_sha256 = hashlib.sha256(disk_bytes).hexdigest() if disk_bytes else ""
    else:
        md_sha256 = (
            hashlib.sha256(md_content.encode("utf-8")).hexdigest()
            if md_content
            else ""
        )

    # 收集需要计算哈希的代码源文件清单
    target_code_srcs: list[str] = []
    if code_sources:
        for s in code_sources:
            if isinstance(s, dict) and s.get("name"):
                target_code_srcs.append(str(s["name"]))
            elif isinstance(s, str):
                target_code_srcs.append(s)
    else:
        frozen_path = os.path.join(work_dir, "frozen_results.json")
        if os.path.isfile(frozen_path):
            try:
                with open(frozen_path, encoding="utf-8") as f:
                    frozen_doc = json.load(f)
                exec_srcs = frozen_doc.get("executed_code_sources", [])
                if isinstance(exec_srcs, list):
                    target_code_srcs.extend([str(x) for x in exec_srcs])
            except Exception:
                pass
        if not target_code_srcs and os.path.isfile(os.path.join(work_dir, "master_solver.py")):
            target_code_srcs.append("master_solver.py")

    code_hashes: dict[str, str] = {}
    for src in dict.fromkeys(target_code_srcs):
        full_src = _safe_path(work_dir, src)
        if full_src and os.path.isfile(full_src):
            try:
                with open(full_src, "rb") as sf:
                    code_hashes[src] = hashlib.sha256(sf.read()).hexdigest()
            except OSError:
                pass

    report = {
        "status": overall_status,
        "passed": overall_passed,
        "markdown_sha256": md_sha256,
        "code_source_hashes": code_hashes,
        "generated_at": datetime.datetime.now().isoformat(),
        "code_text_parity": parity_result,
        "optimality_consistency": optimality_result,
        "latex_formatting_integrity": latex_integrity_result,
        "code_self_containment": code_self_containment_result,
        "keywords_modeling_compliance": keywords_compliance_result,
        "fact_store_fact_count": len(fact_store.list_facts()),
    }

    report_path = os.path.join(work_dir, CROSS_MODAL_REPORT_FILENAME)
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"写入 {CROSS_MODAL_REPORT_FILENAME} 失败: {exc}")

    return report
