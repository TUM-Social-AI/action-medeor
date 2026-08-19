FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY benchmarks/embeddings/requirements.txt /tmp/embedding-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/embedding-requirements.txt

COPY apps/backend/app apps/backend/app
COPY benchmarks/embeddings benchmarks/embeddings

ENV PYTHONPATH=/workspace/apps/backend

CMD ["python", "benchmarks/embeddings/run.py"]
