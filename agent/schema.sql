-- Agent database. Run as the postgres superuser (scripts\install.ps1 does this for you):
--   psql -U postgres -v agent_password=your-password -f schema.sql
-- Safe to re-run: it creates only what is missing and resets the agent user's password.

SELECT format('CREATE ROLE agent LOGIN PASSWORD %L', :'agent_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent') \gexec

SELECT format('ALTER ROLE agent LOGIN PASSWORD %L', :'agent_password') \gexec

SELECT 'CREATE DATABASE inventory ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'inventory') \gexec

\c inventory

CREATE TABLE IF NOT EXISTS machines (
  id uuid PRIMARY KEY,
  hostname text,
  os text,
  last_seen timestamptz
);

CREATE TABLE IF NOT EXISTS services (
  machine_id uuid REFERENCES machines(id),
  name text,
  display_name text,
  status text,
  start_type text,
  collected_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processes (
  machine_id uuid REFERENCES machines(id),
  name text,
  pid int,
  path text,
  version text,
  collected_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS listening_ports (
  machine_id uuid REFERENCES machines(id),
  protocol text,
  local_address text,
  port int,
  pid int,
  process_name text,
  path text,
  version text,
  collected_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS installed_software (
  machine_id uuid REFERENCES machines(id),
  name text,
  version text,
  publisher text,
  collected_at timestamptz DEFAULT now()
);

-- Index names match the ones PostgreSQL generated before, so re-running on an older database adds nothing.
CREATE INDEX IF NOT EXISTS listening_ports_machine_id_collected_at_idx ON listening_ports (machine_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS services_machine_id_collected_at_idx ON services (machine_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS processes_machine_id_collected_at_idx ON processes (machine_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS installed_software_machine_id_collected_at_idx ON installed_software (machine_id, collected_at DESC);

GRANT USAGE ON SCHEMA public TO agent;
GRANT INSERT, UPDATE, SELECT ON ALL TABLES IN SCHEMA public TO agent;
