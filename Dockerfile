FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir '.[dashboard]'

EXPOSE 8501

CMD ["streamlit", "run", "src/creditdelta_mcp/dashboard.py", "--server.address=0.0.0.0"]
