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
