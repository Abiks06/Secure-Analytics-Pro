#!/bin/sh
# Creates the least-privilege application role. It owns the schema objects it creates
# (so tables are created by it), but FORCE ROW LEVEL SECURITY applies RLS to owners too,
# and the role is neither SUPERUSER nor BYPASSRLS.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE sap_app LOGIN PASSWORD '${SAP_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO sap_app;
GRANT USAGE, CREATE ON SCHEMA public TO sap_app;
SQL
