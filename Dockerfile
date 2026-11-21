# 知微 ZhiWei · 运行镜像
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# uv 安装依赖更快，且尊重 pyproject.toml
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

RUN uv pip install --system --no-cache .

EXPOSE 8420

# Render 会注入 PORT；本地默认 8420
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8420}"]
