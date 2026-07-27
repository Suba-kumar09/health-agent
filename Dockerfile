FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY agent ./agent
COPY server ./server

RUN pip install --no-cache-dir ".[server]"

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn server.main:app --host 0.0.0.0 --port 8000"]
