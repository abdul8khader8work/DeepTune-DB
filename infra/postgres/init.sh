#!/bin/bash
# Target DB initialisation: demo schema + the read-only query_optimizer role.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -f /opt/deeptune/demo.sql

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -v ro_user="${TARGET_RO_USER:-query_optimizer}" \
    -v ro_password="${TARGET_RO_PASSWORD:?TARGET_RO_PASSWORD must be set}" \
    -v target_db="$POSTGRES_DB" \
    -f /opt/deeptune/grants.sql
