# syntax=docker/dockerfile:1.7

# Non-production bundled-stack database. Release automation must resolve the base and resulting
# images by digest before promotion.
ARG PGVECTOR_BASE_IMAGE=pgvector/pgvector:0.8.1-pg16-bookworm
FROM ${PGVECTOR_BASE_IMAGE}

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends libnss-wrapper \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/postgresql/data /var/run/postgresql \
    && chgrp -R 0 /var/lib/postgresql /var/run/postgresql \
    && chmod -R g=u /var/lib/postgresql /var/run/postgresql

COPY deploy/postgres-openshift-entrypoint.sh /usr/local/bin/postgres-openshift-entrypoint.sh

RUN chmod 0555 /usr/local/bin/postgres-openshift-entrypoint.sh

ENV HOME=/tmp \
    PGDATA=/var/lib/postgresql/data/pgdata

USER 10001

ENTRYPOINT ["/usr/local/bin/postgres-openshift-entrypoint.sh"]
CMD ["postgres"]
