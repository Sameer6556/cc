# Teacher-labelling worker and clean.py. Build from the repository root:
#   docker build -f worker/Dockerfile -t teacher-worker:0.1.0 .
# Behind a TLS-intercepting proxy, add: --secret id=extra_ca,src=/path/to/proxy-ca.pem
FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY worker/requirements.txt .
RUN --mount=type=secret,id=extra_ca \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-deps -r requirements.txt
COPY data/schema.json /app/schema.json
COPY prompts/teacher_prompt.txt /app/prompts/teacher_prompt.txt
COPY worker/s3io.py worker/teacher.py worker/worker.py worker/clean.py /app/
RUN useradd --uid 10001 --create-home worker
USER 10001
CMD ["python", "worker.py"]
