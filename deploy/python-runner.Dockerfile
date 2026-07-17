FROM python:3.13-slim@sha256:bffeb7bd6a85767587059c6ba23e1e9122078e3aa3fa836099171b9bb5a9bb00

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHON_NODE_RUNNER_MAX_EXECUTIONS=20 \
    PYTHON_NODE_RUNNER_MAX_AGE_SECONDS=900

WORKDIR /runner
COPY apps/workflows/python_node_runner_service.py /runner/python_node_runner_service.py
COPY apps/workflows/python_node_worker.py /runner/python_node_worker.py

RUN useradd --no-create-home --uid 10001 runner \
    && chown -R 10001:0 /runner \
    && chmod -R g=u /runner

USER 10001
EXPOSE 8080
CMD ["python", "-I", "/runner/python_node_runner_service.py"]
