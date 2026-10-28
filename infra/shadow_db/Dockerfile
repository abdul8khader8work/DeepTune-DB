# Shadow database: stock PostgreSQL 16 plus the hypopg extension.
# The data directory is mounted on tmpfs by docker-compose, so hypothetical
# indexes never touch durable storage.
FROM postgres:16-bookworm

RUN set -eux; \
    if [ -x /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh ]; then \
        yes | /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-16-hypopg; \
    rm -rf /var/lib/apt/lists/*

COPY init/00-hypopg.sql /docker-entrypoint-initdb.d/00-hypopg.sql
