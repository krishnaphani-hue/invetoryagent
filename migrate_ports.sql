-- Adds port/version support to an existing database. Run as postgres:
--   psql -U postgres -d inventory -f migrate_ports.sql
ALTER TABLE processes ADD COLUMN IF NOT EXISTS version text;

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
CREATE INDEX IF NOT EXISTS listening_ports_machine_time ON listening_ports (machine_id, collected_at DESC);

GRANT INSERT, UPDATE, SELECT ON ALL TABLES IN SCHEMA public TO agent;
