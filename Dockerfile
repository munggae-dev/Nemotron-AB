FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt /app/requirements-docker.txt
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-docker.txt

COPY app /app/app
COPY script /app/script
COPY apps/api /app/apps/api
COPY apps/__init__.py /app/apps/__init__.py

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8010
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8010"]
