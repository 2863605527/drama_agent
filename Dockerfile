# ============================================================
# 阶段 1：构建前端（Vue3 + Vite）。产出 frontend/dist
# 服务器 git clone 后无需本机安装 Node，镜像内完成前端构建
# ============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /fe

# 先拷依赖清单利用缓存层；npm ci 按 package-lock.json 精确安装
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# 拷源码并构建（.dockerignore 已排除 node_modules/.vite）
COPY frontend/ ./
RUN npm run build

# ============================================================
# 阶段 2：Python 运行时
# ============================================================
FROM python:3.11-slim

# 系统依赖：curl 用于健康检查；ffmpeg 由 imageio-ffmpeg 自带，无需系统安装
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker 缓存层，代码变更不重新 pip install）
# 优先用 requirements.lock 精确锁定版本，保证本地/线上构建结果一致
COPY requirements.txt requirements.lock ./
RUN if [ -f requirements.lock ]; then \
        pip install --no-cache-dir -r requirements.lock; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# 复制应用代码
COPY . .

# 用阶段 1 构建出的前端产物覆盖（保证镜像内一定有最新 dist，不依赖宿主机是否 build 过）
COPY --from=frontend-builder /fe/dist ./frontend/dist

# 运行时目录（通过 volume 挂载到宿主机持久化）
RUN mkdir -p assets storage logs

EXPOSE 8010

# 健康检查：访问真实健康端点（探测应用 + MySQL）
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD curl -f http://localhost:8010/health || exit 1

# 生产默认用 gunicorn 多 worker；开发可覆盖 CMD 为 uvicorn --reload
# WEB_CONCURRENCY 控制 worker 数（默认见 gunicorn_conf.py）
CMD ["gunicorn", "main:app", "-c", "gunicorn_conf.py"]
