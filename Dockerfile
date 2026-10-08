FROM python:3.11-slim

# System dependencies for lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create a non-root user
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Data directory for SQLite WAL database
VOLUME ["/app/data"]

ENV DB_PATH=/app/data/jobs.db
ENV JSON_FALLBACK_PATH=/app/data/jobs_fallback.json

ENTRYPOINT ["python", "bot.py"]
CMD []
