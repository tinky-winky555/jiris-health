-- Cluster bootstrap, run once by the superuser (TDD section 9.1, D29).
-- A template: the passwords are psql variables, set by docker/postgres/init.sh from the
-- container environment (.env) and by the test fixtures with random values (TD-1, DL-38).
-- Schemas, tables and DML grants are created by the Alembic chains under jiris_migrator.
CREATE ROLE jiris_migrator LOGIN PASSWORD :'migrator_password';
CREATE ROLE visits_app LOGIN PASSWORD :'visits_password';
CREATE ROLE billing_app LOGIN PASSWORD :'billing_password';

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO jiris_migrator', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO visits_app, billing_app', current_database());
END
$$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
