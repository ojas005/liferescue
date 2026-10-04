-- DEV ONLY. Least-privilege application role (SECURITY A6) and a separate DB for pytest.
-- The POSTGRES_USER (liferescue) is the schema OWNER used by Alembic; the app should connect as liferescue_app.
CREATE ROLE liferescue_app LOGIN PASSWORD 'liferescue_app_dev' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE liferescue TO liferescue_app;
CREATE DATABASE liferescue_test OWNER liferescue;
GRANT CONNECT ON DATABASE liferescue_test TO liferescue_app;
