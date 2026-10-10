# syntax=docker/dockerfile:1.6
# ===== 构建阶段 =====
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# 系统依赖（编译 cryptography / asyncpg / scapy 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libffi-dev \
        libssl-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock ./
# 使用 poetry.lock 锁定版本，保证构建可复现（M0 升级的 CVE 修复版本真正生效）；无 lock 时回退到 pyproject 解析
RUN poetry install --without dev --no-root

# ===== 运行阶段 =====
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 运行时所需系统包（不含编译器）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        iputils-ping \
        openssh-client \
        curl \
        tzdata \
    && ln -sf /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

# 拷贝构建阶段安装好的 Python 依赖
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 拷贝项目源码
COPY . .
COPY docker-entrypoint.sh /docker-entrypoint.sh

# 数据 / 备份目录 + 非 root 用户
RUN mkdir -p /opt/cornerstone/backups /app/data \
    && chmod +x /docker-entrypoint.sh \
    && useradd -m -u 1000 cornerstone \
    && chown -R cornerstone:cornerstone /app /opt/cornerstone /docker-entrypoint.sh
USER cornerstone

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1

# 入口脚本：先初始化 DB，再启动 uvicorn
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
