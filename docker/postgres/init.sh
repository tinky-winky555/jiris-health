#!/bin/sh
# Renders docker/postgres/init.sql with the role passwords from the container environment
# (TDD section 9.1; TD-1, DL-38). Run once by the postgres image on an empty volume.
set -eu
psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v migrator_password="$JIRIS_MIGRATOR_PASSWORD" \
    -v visits_password="$VISITS_APP_PASSWORD" \
    -v billing_password="$BILLING_APP_PASSWORD" \
    -f /jiris/init.sql
