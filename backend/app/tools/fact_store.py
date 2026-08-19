"""FactStore: 强类型单一事实源与响应式数据绑定管道。

为 MathModelAgent 提供跨智能体、跨阶段的统一数值事实中心，
支持从 frozen_results.json 及结果 CSV 自动提取事实、生成 fact_store.json、
解析文本中的 {{ facts.quesN.metric }} 占位符并校验图文数据一致性。
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.utils.log_util import logger


FACT_STORE_FILENAME = "fact_store.json"
PLACEHOLDER_PATTERN = re.compile(
    r"\{\{\s*facts\.(?P<path>[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*)\s*\}\}"
)


@dataclass
class NumericFact:
    """单一数值事实定义。"""

    name: str
    value: float | int | str
    subtask_id: str | None = None
    unit: str = ""
    label: str = ""
    source: str = ""
    wilson_low: float | None = None
    wilson_high: float | None = None
    confidence_level: float | None = None
    is_optimal: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def format_value(self, precision: int = 4) -> str:
        """格式化数值输出。"""
        if isinstance(self.value, (int, float)):
            if isinstance(self.value, int) or (
                isinstance(self.value, float) and self.value.is_integer()
            ):
                return str(int(self.value))
            formatted = f"{float(self.value):.{precision}f}"
            if "." in formatted:
                formatted = formatted.rstrip("0").rstrip(".")
            return formatted
        return str(self.value)


class FactStore:
    """响应式数值事实中心。"""

    def __init__(self, work_dir: str | None = None) -> None:
        self.work_dir = work_dir
        self._facts: dict[str, NumericFact] = {}

    def register(self, fact: NumericFact) -> None:
        """注册或更新一个数值事实。"""
        key = self._normalize_key(fact.name, fact.subtask_id)
        self._facts[key] = fact

    def register_metric(
        self,
        name: str,
        value: float | int | str,
        subtask_id: str | None = None,
        unit: str = "",
        label: str = "",
        source: str = "",
        wilson_low: float | None = None,
        wilson_high: float | None = None,
        confidence_level: float | None = None,
        is_optimal: bool = False,
        **metadata: Any,
    ) -> NumericFact:
        """便捷注册数值指标。"""
        fact = NumericFact(
            name=name,
            value=value,
            subtask_id=subtask_id,
            unit=unit,
            label=label or name,
            source=source,
            wilson_low=wilson_low,
            wilson_high=wilson_high,
            confidence_level=confidence_level,
            is_optimal=is_optimal,
            metadata=metadata,
        )
        self.register(fact)
        return fact

    def get(self, key: str, subtask_id: str | None = None) -> NumericFact | None:
        """获取数值事实。"""
        normalized = self._normalize_key(key, subtask_id)
        if normalized in self._facts:
            return self._facts[normalized]
        # 回退直接按 key 查找
        if key in self._facts:
            return self._facts[key]
        for stored_key, fact in self._facts.items():
            if fact.name == key or stored_key.endswith(f".{key}"):
                return fact
        return None

    def get_value(
        self,
        key: str,
        subtask_id: str | None = None,
        default: Any = None,
    ) -> Any:
        """获取数值事实的具体值。"""
        fact = self.get(key, subtask_id)
        return fact.value if fact is not None else default

    def list_facts(self, subtask_id: str | None = None) -> list[NumericFact]:
        """列出所有已注册事实，支持按 subtask_id 过滤。"""
        if subtask_id is None:
            return list(self._facts.values())
        norm_subtask = str(subtask_id).lower()
        return [
            f
            for f in self._facts.values()
            if f.subtask_id and str(f.subtask_id).lower() == norm_subtask
        ]

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典结构。"""
        by_subtask: dict[str, dict[str, Any]] = {}
        for _key, fact in self._facts.items():
            st = fact.subtask_id or "global"
            if st not in by_subtask:
                by_subtask[st] = {}
            by_subtask[st][fact.name] = asdict(fact)
        return {
            "version": "1.0",
            "fact_count": len(self._facts),
            "subtasks": by_subtask,
            "flat_facts": {k: asdict(v) for k, v in self._facts.items()},
        }

    def save_to_disk(self, work_dir: str | None = None) -> str:
        """持久化保存至 fact_store.json。"""
        target_dir = work_dir or self.work_dir
        if not target_dir:
            raise ValueError("未指定工作目录，无法保存 FactStore")
        out_path = os.path.join(target_dir, FACT_STORE_FILENAME)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"FactStore 已持久化至: {out_path}")
        return out_path

    @classmethod
    def load_from_disk(cls, work_dir: str) -> FactStore:
        """从工作目录的 fact_store.json 加载。"""
        store = cls(work_dir=work_dir)
        store_path = os.path.join(work_dir, FACT_STORE_FILENAME)
        if os.path.isfile(store_path):
            try:
                with open(store_path, encoding="utf-8") as f:
                    data = json.load(f)
                for _k, item in data.get("flat_facts", {}).items():
                    store.register(NumericFact(**item))
                return store
            except Exception as exc:
                logger.warning(f"从 {store_path} 加载 FactStore 失败: {exc}")

        # 尝试从 frozen_results.json / CSV 恢复构建
        store.populate_from_task_artifacts(work_dir)
        return store

    def populate_from_task_artifacts(self, work_dir: str) -> None:
        """从任务目录的 frozen_results.json 及 CSV 自动填充事实。"""
        self.work_dir = work_dir
        # 1. 尝试从 frozen_results.json 读取
        frozen_path = os.path.join(work_dir, "frozen_results.json")
        if os.path.isfile(frozen_path):
            try:
                with open(frozen_path, encoding="utf-8") as f:
                    frozen_data = json.load(f)
                metrics = frozen_data.get("metrics", [])
                for item in metrics:
                    name = item.get("name") or item.get("key") or item.get("label")
                    if not name:
                        continue
                    val = item.get("value")
                    subtask = item.get("subtask_id") or item.get("question")
                    self.register_metric(
                        name=name,
                        value=val,
                        subtask_id=subtask,
                        unit=item.get("unit", ""),
                        label=item.get("label", name),
                        source=item.get("source_path", "frozen_results.json"),
                        wilson_low=item.get("wilson_low"),
                        wilson_high=item.get("wilson_high"),
                        confidence_level=item.get("confidence_level"),
                    )
            except Exception as exc:
                logger.warning(f"从 frozen_results.json 构建 FactStore 失败: {exc}")

        # 2. 扫描关键结果 CSV 补充指标
        if os.path.isdir(work_dir):
            for fname in sorted(os.listdir(work_dir)):
                if not fname.endswith(".csv"):
                    continue
                fpath = os.path.join(work_dir, fname)
                subtask_match = re.match(r"^(ques\d+)_", fname, re.IGNORECASE)
                subtask_id = subtask_match.group(1).lower() if subtask_match else None
                try:
                    with open(fpath, encoding="utf-8", errors="replace") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            metric_name = (
                                row.get("metric")
                                or row.get("name")
                                or row.get("indicator")
                                or row.get("param")
                            )
                            val_str = (
                                row.get("value")
                                or row.get("result")
                                or row.get("optimal_value")
                            )
                            if metric_name and val_str is not None:
                                try:
                                    val: float | int = (
                                        int(val_str)
                                        if val_str.isdigit()
                                        else float(val_str)
                                    )
                                except ValueError:
                                    val = val_str
                                unit = row.get("unit", "")
                                self.register_metric(
                                    name=metric_name,
                                    value=val,
                                    subtask_id=subtask_id,
                                    unit=unit,
                                    label=row.get("label", metric_name),
                                    source=fname,
                                )
                except Exception:
                    continue

    def render_template(self, template_text: str) -> tuple[str, list[dict[str, Any]]]:
        """解析并渲染 Markdown/文本中的 {{ facts.path.to.metric }} 占位符。"""
        replacements: list[dict[str, Any]] = []

        def _replace_match(match: re.Match) -> str:
            path = match.group("path")
            parts = path.split(".")
            fact = None
            if len(parts) == 1:
                fact = self.get(parts[0])
            elif len(parts) >= 2:
                subtask_id = parts[0]
                metric_name = ".".join(parts[1:])
                fact = self.get(metric_name, subtask_id=subtask_id) or self.get(
                    parts[-1], subtask_id=subtask_id
                )

            if fact is not None:
                formatted = fact.format_value()
                replacements.append(
                    {
                        "placeholder": match.group(0),
                        "path": path,
                        "value": fact.value,
                        "formatted": formatted,
                        "source": fact.source,
                    }
                )
                return formatted
            logger.warning(f"FactStore 未找到占位符对应的事实: {match.group(0)}")
            return match.group(0)

        rendered = PLACEHOLDER_PATTERN.sub(_replace_match, template_text)
        return rendered, replacements

    def generate_narrative_context(self, subtask_id: str | None = None) -> str:
        """生成供 Writer 使用的高质量结构化事实说明块。"""
        facts = self.list_facts(subtask_id)
        if not facts:
            return ""

        title = (
            f"【FactStore 强类型事实中心（{subtask_id}）】"
            if subtask_id
            else "【FactStore 强类型事实中心】"
        )
        lines = [
            title,
            "本题所有数值陈述必须严格对齐以下 FactStore 单一事实源：",
        ]
        for fact in facts:
            val_str = fact.format_value()
            unit_str = f" {fact.unit}" if fact.unit else ""
            ci_str = ""
            if fact.wilson_low is not None and fact.wilson_high is not None:
                ci_str = f" [Wilson 95% CI: {fact.wilson_low:.4f} ~ {fact.wilson_high:.4f}]"
            lines.append(
                f"- `{fact.name}` ({fact.label}): {val_str}{unit_str}{ci_str}（来源: {fact.source}）"
            )
        return "\n".join(lines)

    @staticmethod
    def _normalize_key(name: str, subtask_id: str | None = None) -> str:
        clean_name = str(name).strip().lower().replace(" ", "_").replace("-", "_")
        if subtask_id:
            clean_subtask = str(subtask_id).strip().lower()
            return f"{clean_subtask}.{clean_name}"
        return clean_name
