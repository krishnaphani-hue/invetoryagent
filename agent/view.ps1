# Shows the latest inventory as tables.  Usage: .\view.ps1 [-Rows 20]
param([int]$Rows = 20, [string]$Password = 'change_me')
$env:PGPASSWORD = $Password
$env:PGCLIENTENCODING = 'UTF8'
$psql = 'C:\Program Files\PostgreSQL\16\bin\psql.exe'
$q = @"
\echo == MACHINES
select hostname, os, last_seen from machines order by last_seen desc;
\echo == SERVICES (latest snapshot)
select name, display_name, status, start_type from services
 where collected_at=(select max(collected_at) from services) order by status, name limit $Rows;
\echo == PROCESSES (latest snapshot)
select name, pid, path from processes
 where collected_at=(select max(collected_at) from processes) order by name limit $Rows;
\echo == INSTALLED SOFTWARE (latest snapshot)
select name, version, publisher from installed_software
 where collected_at=(select max(collected_at) from installed_software) order by name limit $Rows;
\echo == SNAPSHOTS
select collected_at, count(*) services from services group by 1 order by 1 desc limit 10;
"@
$q | & $psql -U agent -h localhost -d inventory
