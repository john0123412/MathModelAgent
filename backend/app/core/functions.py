"""工具函数定义模块，为各 Agent 提供可用的工具 schema。"""

# ---- OpenAI 格式（Chat Completions + Responses 共用） ----

coder_tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "This function allows you to execute Python code and retrieve the terminal output. If the code "
            "generates image output, the function will return the text '[image]'. The code is sent to a "
            "Jupyter kernel for execution. The kernel will remain active after execution, retaining all "
            "variables in memory."
            "You cannot show rich outputs like plots or images, but you can store them in the working directory and point the user to them. ",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The code text"}
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_execution_evidence",
            "description": (
                "Record one completed formal quesN through the trusted evidence writer. "
                "Use this only after execute_code has written the result/data files. "
                "Provide task-relative source_path/data_path values; the backend computes "
                "SHA-256 hashes, updates execution_validation.json, and determines feasible. "
                "This is an agent tool, not a Python import or a function available in the notebook."
            ),
            # Constraint bounds are comparison-dependent.  Keeping this tool
            # non-strict lets the model omit irrelevant bounds instead of
            # inventing null-heavy fields solely to satisfy OpenAI strict-mode.
            # The backend remains the authoritative schema/path/hash validator.
            "strict": False,
            "parameters": {
                "type": "object",
                "properties": {
                    "subtask_id": {"type": "string", "description": "Formal question id, e.g. ques1."},
                    "constraints": {
                        "type": "array",
                        "description": "Verifiable constraints. source_path must name an existing task-relative result file.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "actual": {"type": "number"},
                                "comparison": {"type": "string", "enum": ["abs_diff_lte", "lte", "gte", "gt", "lt", "between"]},
                                "target": {"type": ["number", "null"]},
                                "tolerance": {"type": ["number", "null"]},
                                "lower": {"type": ["number", "null"]},
                                "upper": {"type": ["number", "null"]},
                                "unit": {"type": ["string", "null"]},
                                "source_path": {"type": "string"},
                            },
                            "required": ["id", "actual", "comparison", "source_path"],
                        },
                    },
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                                "value": {"type": "number"},
                                "unit": {"type": "string"},
                                "explanation": {"type": "string"},
                                "aliases": {"type": "array", "items": {"type": "string"}},
                                "source_path": {
                                    "type": "string",
                                    "description": "Task-relative numeric result file containing this value.",
                                },
                            },
                            "required": ["id", "label", "value", "unit", "explanation", "source_path"],
                        },
                    },
                    "figures": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "data_path": {"type": "string"},
                                "metric_ids": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["path", "data_path"],
                        },
                    },
                },
                "required": ["subtask_id", "constraints", "metrics", "figures"],
            },
        },
    },
]

writer_tools = [
    {
        "type": "function",
        "function": {
            "name": "search_papers",
            "description": (
                "Search academic papers from multiple scholarly sources. "
                "Optionally include web/background sources when needed."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The query string"},
                    "limit": {
                        "type": ["integer", "null"],
                        "description": "Maximum number of results to return, or null for default.",
                    },
                    "year_from": {
                        "type": ["integer", "null"],
                        "description": "Earliest publication year.",
                    },
                    "year_to": {
                        "type": ["integer", "null"],
                        "description": "Latest publication year.",
                    },
                    "min_citations": {
                        "type": ["integer", "null"],
                        "description": "Minimum citation count for scholarly sources.",
                    },
                    "source_types": {
                        "type": ["array", "null"],
                        "description": (
                            "Allowed source types: journal, conference, preprint, "
                            "book, web; null for all scholarly types."
                        ),
                        "items": {"type": "string"},
                    },
                    "include_web": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Whether to include Tavily web/background results when "
                            "configured, or null to follow settings."
                        ),
                    },
                },
                "required": [
                    "query",
                    "limit",
                    "year_from",
                    "year_to",
                    "min_citations",
                    "source_types",
                    "include_web",
                ],
                "additionalProperties": False,
            },
        },
    },
]

# ---- Anthropic 格式 ----

coder_tools_anthropic = [
    {
        "name": "execute_code",
        "description": "This function allows you to execute Python code and retrieve the terminal output. If the code "
        "generates image output, the function will return the text '[image]'. The code is sent to a "
        "Jupyter kernel for execution. The kernel will remain active after execution, retaining all "
        "variables in memory."
        "You cannot show rich outputs like plots or images, but you can store them in the working directory and point the user to them. ",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The code text"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "record_execution_evidence",
        "description": (
            "Record one completed formal quesN using the trusted evidence writer. "
            "Call it after execute_code has generated result files. The backend computes hashes, "
            "updates the manifest, and determines feasibility."
        ),
        # 与 OpenAI 版保持同等字段约束：Anthropic 模型同样依赖 schema 了解
        # comparison 合法枚举与 metrics 数值类型，否则证据会被后端逐项拒绝。
        "input_schema": {
            "type": "object",
            "properties": {
                "subtask_id": {"type": "string", "description": "Formal question id, e.g. ques1."},
                "constraints": {
                    "type": "array",
                    "description": "Verifiable constraints. source_path must name an existing task-relative result file.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "actual": {"type": "number"},
                            "comparison": {"type": "string", "enum": ["abs_diff_lte", "lte", "gte", "gt", "lt", "between"]},
                            "target": {"type": ["number", "null"]},
                            "tolerance": {"type": ["number", "null"]},
                            "lower": {"type": ["number", "null"]},
                            "upper": {"type": ["number", "null"]},
                            "unit": {"type": ["string", "null"]},
                            "source_path": {"type": "string"},
                        },
                        "required": ["id", "actual", "comparison", "source_path"],
                    },
                },
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "value": {"type": "number"},
                            "unit": {"type": "string"},
                            "explanation": {"type": "string"},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                            "source_path": {
                                "type": "string",
                                "description": "Task-relative numeric result file containing this value.",
                            },
                        },
                        "required": ["id", "label", "value", "unit", "explanation", "source_path"],
                    },
                },
                "figures": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "data_path": {"type": "string"},
                            "metric_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["path", "data_path"],
                    },
                },
            },
            "required": ["subtask_id", "constraints", "metrics", "figures"],
        },
    },
]

writer_tools_anthropic = [
    {
        "name": "search_papers",
        "description": (
            "Search academic papers from multiple scholarly sources. "
            "Optionally include web/background sources when needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The query string"},
                "limit": {
                    "type": ["integer", "null"],
                    "description": "Maximum number of results to return, or null for default.",
                },
                "year_from": {
                    "type": ["integer", "null"],
                    "description": "Earliest publication year.",
                },
                "year_to": {
                    "type": ["integer", "null"],
                    "description": "Latest publication year.",
                },
                "min_citations": {
                    "type": ["integer", "null"],
                    "description": "Minimum citation count for scholarly sources.",
                },
                "source_types": {
                    "type": ["array", "null"],
                    "description": (
                        "Allowed source types: journal, conference, preprint, book, web; "
                        "null for all scholarly types."
                    ),
                    "items": {"type": "string"},
                },
                "include_web": {
                    "type": ["boolean", "null"],
                    "description": (
                        "Whether to include Tavily web/background results when configured, "
                        "or null to follow settings."
                    ),
                },
            },
            "required": [
                "query",
                "limit",
                "year_from",
                "year_to",
                "min_citations",
                "source_types",
                "include_web",
            ],
        },
    },
]
