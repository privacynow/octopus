# Phase 12: canonical development image. Not for production tuning.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application and schema (migrations live in app/db/migrations/postgres)
COPY app ./app
COPY octopus_sdk ./octopus_sdk
COPY skills ./skills
COPY scripts ./scripts

# Default: run the bot (overridden by compose for one-shot db commands)
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "app.main"]
