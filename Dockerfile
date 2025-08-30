FROM python:3.11-slim

# System setup
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy app
COPY api.py .

# Render provides $PORT; default to 8000 for local runs
ENV PORT=8000

# Start the server (bind 0.0.0.0 and use $PORT if provided)
CMD ["sh","-c","uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
