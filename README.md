# Inventory Agent

A background Windows service (C++17, Win32 API, UTF-8) that collects services, running processes,
listening ports with application versions, and installed software, and stores them in PostgreSQL.

## Build
Requires MSVC Build Tools and PostgreSQL 16 (for libpq). Run `build.bat`; output goes to `out\`.

## Database
`psql -U postgres -f schema.sql` for a new database, or `migrate_ports.sql` to add port/version support to an existing one.

## Install
Double-click `out\InventoryAgent.exe` (asks for admin rights, then shows a setup dialog), or use
`InventoryAgent.exe --install | --uninstall | --console`.

## Configure
Edit `config.ini` beside the exe: connection string, interval, software collection on/off.
The sample password `change_me` is a placeholder; change it before real use.

## View data
`.\view.ps1` prints the latest inventory as tables, or use pgAdmin.
