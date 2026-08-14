"""Generate a deterministic matplotlib bootstrap for agent code kernels.

The default E2B/local interpreters run in fresh environments where matplotlib's
font cache may predate task-provided CJK fonts. Keeping this setup in one small
helper lets both runtimes share cache invalidation and figure constants without
changing the execution or evidence contract.
"""

from __future__ import annotations

COLORS: dict[str, str] = {
    "primary": "#2E5B88",
    "secondary": "#E85D4C",
    "tertiary": "#4A9B7F",
    "neutral": "#7F7F7F",
    "light": "#B8D4E8",
}

FIG_SINGLE = (5, 4)
FIG_DOUBLE = (10, 4)
FIG_WIDE = (8, 3)
FIG_SQUARE = (6, 6)


def build_matplotlib_init_code(
    work_dir: str,
    *,
    font_dir: str | None = None,
    setup_chdir: bool = True,
) -> str:
    """Build code executed once when an agent's plotting kernel starts."""
    import os

    # E2B paths are POSIX paths even when the backend itself runs on Windows;
    # do not reinterpret ``/home/user`` through the host OS path semantics.
    def _kernel_path(value: str) -> str:
        return value if value.startswith("/") else os.path.abspath(value)

    absolute_work_dir = _kernel_path(work_dir)
    absolute_font_dir = _kernel_path(font_dir or work_dir)
    code = [
        "import os",
        f"work_dir = {absolute_work_dir!r}",
        f"_font_dir = {absolute_font_dir!r}",
    ]
    if setup_chdir:
        code.extend(
            [
                "os.makedirs(work_dir, exist_ok=True)",
                "os.chdir(work_dir)",
                "print('[matplotlib_setup] 当前工作目录:', os.getcwd())",
            ]
        )

    code.extend(
        [
            "import glob as _glob",
            "import pathlib as _pl",
            "import matplotlib",
            "import matplotlib.pyplot as plt",
            "from matplotlib import font_manager",
            "_cache_dir = _pl.Path(matplotlib.get_cachedir())",
            "for _cache_file in _glob.glob(str(_cache_dir / 'fontlist*.json')):",
            "    _pl.Path(_cache_file).unlink(missing_ok=True)",
            "font_manager.fontManager.__init__()",
            "_cjk_fonts = []",
            "for _f in os.listdir(_font_dir):",
            "    if not _f.lower().endswith(('.ttf', '.otf', '.ttc')):",
            "        continue",
            "    _fp = os.path.join(_font_dir, _f)",
            "    try:",
            "        font_manager.fontManager.addfont(_fp)",
            "        _name = font_manager.FontProperties(fname=_fp).get_name()",
            "    except (OSError, ValueError):",
            "        continue",
            "    if _name not in _cjk_fonts:",
            "        _cjk_fonts.append(_name)",
            "if _cjk_fonts:",
            "    CJK_FONT = _cjk_fonts[0]",
            "    _fallback = ['Heiti SC', 'STHeiti', 'PingFang SC', 'Noto Sans CJK SC', 'Noto Sans SC', 'WenQuanYi Micro Hei', 'Microsoft YaHei', 'sans-serif']",
            "    plt.rcParams['font.sans-serif'] = _cjk_fonts + [f for f in _fallback if f not in _cjk_fonts]",
            "    print(f'[matplotlib_setup] 中文字体已加载: {CJK_FONT} (共 {len(_cjk_fonts)} 个)')",
            "else:",
            "    CJK_FONT = None",
            "    print('[matplotlib_setup] 警告: 未找到中文字体文件，中文标签可能显示为方框')",
            "plt.rcParams['axes.unicode_minus'] = False",
            "plt.rcParams['font.family'] = 'sans-serif'",
            "plt.rcParams.update({",
            "    'font.size': 11,",
            "    'axes.titlesize': 12,",
            "    'axes.titleweight': 'bold',",
            "    'axes.labelsize': 11,",
            "    'axes.linewidth': 1.2,",
            "    'axes.spines.top': False,",
            "    'axes.spines.right': False,",
            "    'xtick.labelsize': 10,",
            "    'ytick.labelsize': 10,",
            "    'legend.fontsize': 10,",
            "    'legend.frameon': False,",
            "    'figure.dpi': 300,",
            "    'savefig.dpi': 300,",
            "    'savefig.bbox': 'tight',",
            "    'savefig.pad_inches': 0.1,",
            "})",
            f"COLORS = {COLORS!r}",
            "DEFAULT_COLORS = list(COLORS.values())",
            f"FIG_SINGLE = {FIG_SINGLE!r}",
            f"FIG_DOUBLE = {FIG_DOUBLE!r}",
            f"FIG_WIDE = {FIG_WIDE!r}",
            f"FIG_SQUARE = {FIG_SQUARE!r}",
            "print('[matplotlib_setup] 绘图环境就绪 (COLORS, FIG_* 已注入)')",
        ]
    )
    return "\n".join(code) + "\n"
