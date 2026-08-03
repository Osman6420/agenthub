# syntax=docker/dockerfile:1.7

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY examples/external-consumer-demo/index.html ./index.html
COPY examples/external-consumer-demo/app.js ./app.js
COPY examples/external-consumer-demo/styles.css ./styles.css
COPY examples/external-consumer-demo/server.py ./server.py

RUN useradd --create-home --uid 10001 demo \
    && find /app -type d -exec chmod 0555 {} + \
    && find /app -type f -exec chmod 0444 {} +

USER 10001

EXPOSE 8080

CMD ["python", "/app/server.py", \
     "--credentials", "/run/secrets/agenthub-demo/credentials.json", \
     "--bind", "0.0.0.0", "--port", "8080", \
     "--allow-network-bind", "--allow-cluster-upstream"]
