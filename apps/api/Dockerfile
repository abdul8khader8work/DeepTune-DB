FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

# Phase 2 runtime, then the CPU-only inference stack. The CPU index keeps the
# image small; there is no CUDA in this container.
COPY apps/api/requirements.txt ./requirements.txt
COPY apps/api/requirements-ml.txt ./requirements-ml.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    -r requirements-ml.txt

# The engine is a pure library: PyTorch/PyG math plus symbolic search.
# Weights are mounted at runtime (they are git-ignored); if the mount is empty
# the API logs a warning and degrades to the heuristic recommender.
COPY packages/ml-engine/src /app/packages/ml-engine/src
COPY apps/api/src ./src

ENV ML_ENABLED=true \
    ML_ENGINE_SRC=/app/packages/ml-engine/src \
    ML_CHECKPOINT_PATH=/app/packages/ml-engine/weights/demo-final.pt \
    ML_DEVICE=cpu \
    ML_ATTENTION_NODES=10

USER appuser
EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
