"""数模竞赛经典权威教材候选池与文献元数据定义。

为写作手提供规范、真实、公认的经典教材引用建议，防止无外网文献检索时大模型幻觉编造假文献。
"""

from typing import Any

AUTHORITATIVE_TEXTBOOKS: list[dict[str, Any]] = [
    {
        "id": "jiang_math_model",
        "title": "数学模型",
        "authors": "姜启源, 谢金星, 叶俊",
        "publisher": "北京: 高等教育出版社",
        "year": "2018",
        "edition": "第5版",
        "citation": "姜启源, 谢金星, 叶俊. 数学模型[M]. 第5版. 北京: 高等教育出版社, 2018.",
        "domains": ["初等模型", "微分方程与差分方程", "图论与网络", "几何与物理建模", "综合评价与决策"],
    },
    {
        "id": "si_math_model_algo",
        "title": "数学建模算法与应用",
        "authors": "司守奎, 孙兆亮",
        "publisher": "北京: 国防工业出版社",
        "year": "2021",
        "edition": "第3版",
        "citation": "司守奎, 孙兆亮. 数学建模算法与应用[M]. 第3版. 北京: 国防工业出版社, 2021.",
        "domains": ["线性与非线性规划", "混合整数规划", "多目标规划", "启发式算法", "时间序列分析", "多元统计分析"],
    },
    {
        "id": "tsinghua_operations_research",
        "title": "运筹学",
        "authors": "《运筹学》教材编写组",
        "publisher": "北京: 清华大学出版社",
        "year": "2020",
        "edition": "第5版",
        "citation": "《运筹学》教材编写组. 运筹学[M]. 第5版. 北京: 清华大学出版社, 2020.",
        "domains": ["单纯形法", "对偶理论与灵敏度分析", "运输问题", "动态规划", "排队论", "存贮论"],
    },
    {
        "id": "vanderbei_linear_programming",
        "title": "Linear Programming: Foundations and Extensions",
        "authors": "Vanderbei R J",
        "publisher": "Cham: Springer",
        "year": "2020",
        "edition": "5th ed.",
        "doi": "10.1007/978-3-030-39415-8",
        "citation": "Vanderbei R J. Linear Programming: Foundations and Extensions[M]. 5th ed. Cham: Springer, 2020.",
        "domains": ["Linear Programming", "Duality Theory", "Interior Point Methods", "Network Flows", "Optimization"],
    },
    {
        "id": "boyd_convex_optimization",
        "title": "Convex Optimization",
        "authors": "Boyd S, Vandenberghe L",
        "publisher": "Cambridge: Cambridge University Press",
        "year": "2004",
        "edition": "1st ed.",
        "citation": "Boyd S, Vandenberghe L. Convex Optimization[M]. Cambridge: Cambridge University Press, 2004.",
        "domains": ["Convex Optimization", "Lagrange Duality", "KKT Conditions", "Semidefinite Programming"],
    },
    {
        "id": "li_statistical_learning",
        "title": "统计学习方法",
        "authors": "李航",
        "publisher": "北京: 清华大学出版社",
        "year": "2019",
        "edition": "第2版",
        "citation": "李航. 统计学习方法[M]. 第2版. 北京: 清华大学出版社, 2019.",
        "domains": ["感知机与SVM", "朴素贝叶斯与决策树", "EM算法", "隐马尔可夫模型", "无监督学习与聚类"],
    },
]

STANDARD_DEFAULT_TEXTBOOK_CITATIONS: list[str] = [
    str(book["citation"]) for book in AUTHORITATIVE_TEXTBOOKS
]


def get_textbook_citation_pool_prompt(max_items: int = 6) -> str:
    """生成用于 Writer Prompt 的权威教材候选池说明与条目列表。"""
    items = AUTHORITATIVE_TEXTBOOKS[:max_items]
    lines = [
        "### 经典权威教材候选池（基础方法保底引用建议）",
        "若本节使用了基础运筹学、优化理论、数理统计或经典建模算法，且未检索到针对性前沿学术论文，"
        "可选用以下预核准经典教材按标准国标格式引用；严禁编造未经核验的其他书目或虚构作者/出版社：",
    ]
    for idx, book in enumerate(items, start=1):
        domains_str = "/".join(book["domains"][:3])
        lines.append(f"[{idx}] {book['citation']} （适用领域: {domains_str}）")
    return "\n".join(lines)
