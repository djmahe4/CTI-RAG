# 使用Python 3.11作为基础镜像
# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

# 直接从官方镜像复制 uv 可执行文件，避免在构建阶段额外安装
COPY --from=ghcr.nju.edu.cn/astral-sh/uv:latest /uv /uvx /bin/

# 设置工作目录
WORKDIR /app

# 设置清华镜像源加速Debian包下载
RUN echo 'deb https://mirrors.tuna.tsinghua.edu.cn/debian/ trixie main contrib non-free-firmware' > /etc/apt/sources.list && \
    echo 'deb https://mirrors.tuna.tsinghua.edu.cn/debian-security/ trixie-security main contrib non-free-firmware' >> /etc/apt/sources.list && \
    echo 'deb https://mirrors.tuna.tsinghua.edu.cn/debian/ trixie-updates main contrib non-free-firmware' >> /etc/apt/sources.list

# 安装系统依赖
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    default-libmysqlclient-dev \
    default-mysql-client \
    curl \
    netcat-openbsd \
    redis-tools \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    antiword \
    && rm -rf /var/lib/apt/lists/*

# 复制 API 运行时 requirements 文件
COPY requirements-api.txt .

# 安装Python依赖（使用清华PyPI镜像加速）
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_HTTP_TIMEOUT=300 \
    uv pip install --system -r requirements-api.txt

# 单独安装 CPU 版 PyTorch，避免默认安装拉取 CUDA 依赖
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    UV_INDEX_URL=https://download.pytorch.org/whl/cpu \
    UV_HTTP_TIMEOUT=300 \
    uv pip install --system torch==2.5.1

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p /app/data /app/models /app/saves/log

# 设置Python路径
ENV PYTHONPATH=/app

# 设置默认环境变量
ENV FASTAPI_ENV=production

# 暴露端口
EXPOSE 8006

# 复制启动脚本
COPY scripts/start.sh /app/start.sh
RUN chmod +x /app/start.sh || true
RUN sed -i 's/\r$//' /app/start.sh || true

# 启动命令
CMD ["bash", "/app/start.sh"]
