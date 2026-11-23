-- Run as the postgres superuser:  psql -U postgres -f schema.sql
-- Change the password before real use.
CREATE DATABASE inventory;
CREATE USER agent WITH PASSWORD 'change_me';
\c inventory

CREATE TABLE machines (
  id uuid PRIMARY KEY,
  hostname text,
  os text,
  last_seen timestamptz
);

CREATE TABLE services (
  machine_id uuid REFERENCES machines(id),
  name text,
  display_name text,
  status text,
  start_type text,
  collected_at timestamptz DEFAULT now()
);

CREATE TABLE processes (
  machine_id uuid REFERENCES machines(id),
  name text,
  pid int,
  path text,
  version text,
  collected_at timestamptz DEFAULT now()
);

CREATE TABLE listening_ports (
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
CREATE INDEX ON listening_ports (machine_id, collected_at DESC);

CREATE TABLE installed_software (
  machine_id uuid REFERENCES machines(id),
  name text,
  version text,
  publisher text,
  collected_at timestamptz DEFAULT now()
);

CREATE INDEX ON services (machine_id, collected_at DESC);
CREATE INDEX ON processes (machine_id, collected_at DESC);
CREATE INDEX ON installed_software (machine_id, collected_at DESC);

GRANT USAGE ON SCHEMA public TO agent;
GRANT INSERT, UPDATE, SELECT ON ALL TABLES IN SCHEMA public TO agent;
