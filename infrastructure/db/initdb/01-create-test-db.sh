#!/bin/sh
# Runs once, on first initialisation of an empty data volume (postgres image entrypoint contract).
# Creates the separate database used by automated tests so tests never touch the development data.
# Inputs come from the container environment (POSTGRES_USER, POSTGRES_TEST_DB); no secrets are read or printed.
# Written to work whether the entrypoint executes it or sources it (no `exit` statements).
set -eu

if [ -z "${POSTGRES_TEST_DB:-}" ]; then
  echo "initdb: POSTGRES_TEST_DB is empty - skipping test database creation"
else
  # format('%I') quotes the identifier, so the name cannot inject SQL; \gexec runs the generated statement.
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -v testdb="$POSTGRES_TEST_DB" <<'SQL'
SELECT format('CREATE DATABASE %I', :'testdb') WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'testdb') \gexec
SQL
  echo "initdb: test database ensured: ${POSTGRES_TEST_DB}"
fi
