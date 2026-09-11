FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package terrasentry-api --no-dev
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "alembic -c apps/api/alembic.ini upgrade head && fastapi run apps/api/src/terrasentry_api/main.py --host 0.0.0.0 --port 8000"]
