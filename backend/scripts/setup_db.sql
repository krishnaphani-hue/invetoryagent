-- One-time database setup. Run as the postgres superuser, e.g. via scripts/setup_db.ps1,
-- or paste into pgAdmin's Query Tool (replace :'app_password' with a quoted password).
--   psql -U postgres -p 5433 -v app_password='your-password' -f backend/scripts/setup_db.sql
-- Safe to re-run: it only creates what is missing and resets the app user's password.

SELECT format('CREATE ROLE inventory_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'inventory_app') \gexec

SELECT format('ALTER ROLE inventory_app LOGIN PASSWORD %L', :'app_password') \gexec

SELECT 'CREATE DATABASE asset_inventory OWNER inventory_app ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'asset_inventory') \gexec

SELECT 'CREATE DATABASE asset_inventory_test OWNER inventory_app ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'asset_inventory_test') \gexec
