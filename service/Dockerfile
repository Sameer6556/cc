# Command-parser inference service (Task 3). Build from the repository root:
#   docker build -f service/Dockerfile -t parser-service:0.1.0 .          (or: make image)
# The image contains code and pinned libraries only. The model weights are NOT in the image:
# the service downloads them from object storage (MODEL_URI) at start-up.
# Behind a TLS-intercepting proxy, add: --secret id=extra_ca,src=/path/to/proxy-ca.pem
FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app
COPY service/requirements.txt .
# CPU-only PyTorch wheel (the default PyPI wheel bundles CUDA libraries and is several GB),
# then every other dependency exactly as pinned in the lock file.
RUN --mount=type=secret,id=extra_ca \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-deps --index-url https://download.pytorch.org/whl/cpu torch==2.14.1+cpu \
 && pip install --no-deps -r requirements.txt \
 && pip check

COPY data/schema.json /app/schema.json
COPY service/app.py service/parser_core.py /app/
RUN python -c "import app" \
 && useradd --uid 10001 --create-home app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--timeout-graceful-shutdown", "20"]
