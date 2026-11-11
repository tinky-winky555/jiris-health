-- Cluster bootstrap, run once by the superuser (TDD section 9, D29).
-- Schemas, tables and DML grants are created by the Alembic chains under jiris_migrator.
-- Passwords are for local development and tests only.
CREATE ROLE jiris_migrator LOGIN PASSWORD 'jiris_migrator';
CREATE ROLE visits_app LOGIN PASSWORD 'visits_app';
CREATE ROLE billing_app LOGIN PASSWORD 'billing_app';

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO jiris_migrator', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO visits_app, billing_app', current_database());
END
$$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
