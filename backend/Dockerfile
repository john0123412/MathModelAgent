# 使用官方推荐的 Python 基础镜像
FROM python:3.12-slim AS builder

# 是否安装 Microsoft Core Fonts（ttf-mscorefonts-installer，仅含 Times New
# Roman/Courier New/Arial 等英文字体，不含任何中文字体）。默认关闭：该包
# 安装时需要接受 Microsoft 的字体许可协议（EULA），且会在构建时从外部镜像
# 下载字体二进制文件，不适合作为默认公开镜像的行为。仅在私有构建、且已
# 知晓并接受该许可与网络依赖的前提下，显式传入 --build-arg
# INSTALL_MS_FONTS=true 开启。注意：SimSun/SimHei/KaiTi 等中文 Windows
# 字体不受此选项影响，容器内始终 fallback 到 fonts-noto-cjk/
# texlive-lang-chinese 提供的开源等效字体（无法"补装"官方中文字体）。
ARG INSTALL_MS_FONTS=false
ARG UV_VERSION=0.11.14

# 安装中文字体（确保 matplotlib 图表中文正常显示）
# 以及 pandoc + LaTeX 工具链（md -> docx/pdf 转换、xelatex 编译 LaTeX sidecar/gmcmthesis 模板）
# fontconfig：提供 fc-match，供 app.utils.font_utils 在运行时检测正式字体是否
# 存在，缺失时回退到等效字体，而不是在配置里无条件替换正式字体名：
#   - 英文/Latin（Times New Roman/Courier New/Arial）缺失时回退到本层装的
#     fonts-liberation；上面的 INSTALL_MS_FONTS 选项可以补装真正的英文原版
#     字体，从而不必 fallback。
#   - 中文（SimSun/SimHei/KaiTi 等）缺失时回退到本层装的 fonts-noto-cjk /
#     texlive-lang-chinese（AR PL KaitiM GB）。这些中文 Windows 字体没有
#     可合法分发的安装包，INSTALL_MS_FONTS 对中文字体没有作用。
# lmodern：pandoc 默认 LaTeX 模板依赖 lmodern.sty，texlive-latex-recommended
# 未包含该包，缺失会导致直接 PDF 导出（pdf_exporter.py）编译失败
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    fontconfig \
    fonts-liberation \
    pandoc \
    latexmk \
    texlive-xetex \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-lang-chinese \
    texlive-plain-generic \
    lmodern \
    && rm -rf /var/lib/apt/lists/*

# 可选：安装 Microsoft Core Fonts（仅 Times New Roman/Courier New/Arial 等
# 英文字体，不含中文字体）。默认不执行（INSTALL_MS_FONTS=false 时整段被
# shell 短路跳过）。开启后会通过 debconf-set-selections 预先接受 EULA 以
# 实现非交互安装，并从 ttf-mscorefonts-installer 包内置的下载源（非本仓库
# 维护）获取字体文件。
RUN if [ "$INSTALL_MS_FONTS" = "true" ]; then \
        apt-get update && \
        echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections && \
        apt-get install -y --no-install-recommends ttf-mscorefonts-installer && \
        rm -rf /var/lib/apt/lists/*; \
    else \
        echo "跳过 Microsoft Core Fonts 安装（INSTALL_MS_FONTS=$INSTALL_MS_FONTS）：英文字体 fallback 到 fonts-liberation，中文字体不受此选项影响，始终 fallback 到 fonts-noto-cjk/texlive-lang-chinese"; \
    fi

# 安装 uv。避免使用 ghcr.io/astral-sh/uv:latest 作为额外构建阶段：
# 在网络不稳定环境中，GHCR token 获取失败会导致即使 Python 基础镜像已有缓存也
# 无法构建。固定 PyPI 版本也避免 latest 漂移；pip 下载使用较长超时和重试，
# 降低大 wheel 在弱网下中途 read timeout 的概率。
RUN python -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --retries 8 \
    --timeout 120 \
    "uv==${UV_VERSION}"

WORKDIR /app

# 先复制依赖文件，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./

# 安装依赖（不安装项目本身，加快后续构建）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

# 再复制项目代码
COPY . .

# 运行时刷新可选挂载字体目录的 fontconfig 缓存。这样 Windows 用户可以把
# C:\Windows\Fonts 只读挂进容器，让 Docker PDF 优先命中 Times New
# Roman/SimSun/SimHei/KaiTi 等本机合法安装的正式字体，而不是退回开源字体。
COPY docker-entrypoint.sh /usr/local/bin/mma-backend-entrypoint
RUN chmod +x /usr/local/bin/mma-backend-entrypoint

# 安装项目本身
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

EXPOSE 8000

# 直接使用 uvicorn，因为依赖已安装到系统 Python
ENTRYPOINT ["mma-backend-entrypoint"]
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-ping-interval", "60", "--ws-ping-timeout", "120"]
