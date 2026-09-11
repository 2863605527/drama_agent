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

# 运行时目录（通过 volume 挂载到宿主机持久化）
RUN mkdir -p assets storage logs

EXPOSE 8010

# 健康检查：访问真实健康端点（探测应用 + MySQL）
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD curl -f http://localhost:8010/health || exit 1

# 生产默认用 gunicorn 多 worker；开发可覆盖 CMD 为 uvicorn --reload
# WEB_CONCURRENCY 控制 worker 数（默认见 gunicorn_conf.py）
CMD ["gunicorn", "main:app", "-c", "gunicorn_conf.py"]
