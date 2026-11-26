FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /workspace

# Create non-root runtime user
RUN useradd --create-home --shell /bin/bash appuser

COPY pyproject.toml README.md server.py ./
COPY app/ ./app/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && chown -R appuser:appuser /workspace

USER appuser

EXPOSE 8080

CMD ["python", "server.py"]
