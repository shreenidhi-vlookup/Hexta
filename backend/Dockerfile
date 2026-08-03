FROM python:3.11-slim

# Install system deps for psycopg (pg_config) and onnxruntime
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run with single worker as required by CLAUDE.md rule 4
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--workers", "1", "--host", "0.0.0.0", "--port", "8001"]
