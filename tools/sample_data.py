"""Realistic Windows inventory used by make_sample_excel.py and fake_collector.py."""
import random
import uuid

MACHINES = [
    {"id": "43690069-62f5-4a7c-b02a-c0dd35ba4901", "hostname": "FIN-LAPTOP-042", "os": "Windows 11 Enterprise 10.0.26300"},
    {"id": "7d2c9e41-1f3a-4b8e-9c55-2a6d1e0f7b12", "hostname": "DEV-WS-017", "os": "Windows 11 Pro 10.0.26100"},
    {"id": "b5e8a3c2-6d4f-4a19-8e2b-3f7c9d1a0e23", "hostname": "SRV-APP-03", "os": "Windows Server 2022 10.0.20348"},
]

COMMON_SOFTWARE = [
    ("Google Chrome", "131.0.6778.86", "Google LLC"),
    ("Microsoft Edge", "131.0.2903.70", "Microsoft Corporation"),
    ("Microsoft 365 Apps for enterprise - en-us", "16.0.18129.20158", "Microsoft Corporation"),
    ("Microsoft OneDrive", "24.226.1110.0004", "Microsoft Corporation"),
    ("7-Zip 24.08 (x64)", "24.08", "Igor Pavlov"),
    ("Notepad++ (64-bit x64)", "8.7.1", "Notepad++ Team"),
    ("CrowdStrike Windows Sensor", "7.19.18913.0", "CrowdStrike, Inc."),
    ("GlobalProtect", "6.2.4.838", "Palo Alto Networks"),
    ("Microsoft Visual C++ 2015-2022 Redistributable (x64)", "14.40.33810.0", "Microsoft Corporation"),
]

EXTRA_SOFTWARE = {
    "FIN-LAPTOP-042": [("Adobe Acrobat (64-bit)", "24.004.20220", "Adobe"), ("Zoom Workplace (64-bit)", "6.2.11.50410", "Zoom Video Communications, Inc.")],
    "DEV-WS-017": [("Python 3.12.7 (64-bit)", "3.12.7150.0", "Python Software Foundation"),
                   ("Git", "2.47.0", "The Git Development Community"),
                   ("Microsoft Visual Studio Code", "1.95.3", "Microsoft Corporation"),
                   ("Node.js", "22.11.0", "Node.js Foundation"),
                   ("PostgreSQL 16", "16.4-1", "PostgreSQL Global Development Group"),
                   ("Microsoft .NET Runtime - 8.0.10 (x64)", "8.0.10", "Microsoft Corporation"),
                   ("Microsoft .NET Runtime - 6.0.35 (x64)", "6.0.35", "Microsoft Corporation")],
    "SRV-APP-03": [("Microsoft SQL Server 2019 (64-bit)", "15.0.2000.5", "Microsoft Corporation"),
                   ("Apache Tomcat 9.0", "9.0.96", "The Apache Software Foundation"),
                   ("OpenSSL 3.0.13 (64-bit)", "3.0.13", "OpenSSL Win64 Installer Team"),
                   ("Microsoft .NET Runtime - 8.0.10 (x64)", "8.0.10", "Microsoft Corporation")],
}

COMMON_PORTS = [
    ("TCP", "0.0.0.0", 135, 1160, "svchost.exe", r"C:\Windows\System32\svchost.exe", "10.0.26100.1"),
    ("TCP", "0.0.0.0", 445, 4, "System", None, None),
    ("TCP", "0.0.0.0", 5985, 4, "System", None, None),
    ("TCP6", "::", 135, 1160, "svchost.exe", r"C:\Windows\System32\svchost.exe", "10.0.26100.1"),
    ("UDP", "0.0.0.0", 5353, 2264, "svchost.exe", r"C:\Windows\System32\svchost.exe", "10.0.26100.1"),
    ("TCP", "127.0.0.1", 49670, 5020, "CSFalconService.exe", r"C:\Program Files\CrowdStrike\CSFalconService.exe", "7.19.18913.0"),
]

EXTRA_PORTS = {
    "FIN-LAPTOP-042": [("TCP", "0.0.0.0", 3389, 1240, "svchost.exe", r"C:\Windows\System32\svchost.exe", "10.0.26100.1")],
    "DEV-WS-017": [("TCP", "127.0.0.1", 5432, 3120, "postgres.exe", r"C:\Program Files\PostgreSQL\16\bin\postgres.exe", "16.4"),
                   ("TCP", "0.0.0.0", 3000, 8840, "node.exe", r"C:\Program Files\nodejs\node.exe", "22.11.0"),
                   ("TCP", "127.0.0.1", 8000, 9120, "python.exe", r"C:\Python312\python.exe", "3.12.7")],
    "SRV-APP-03": [("TCP", "0.0.0.0", 1433, 2210, "sqlservr.exe", r"C:\Program Files\Microsoft SQL Server\MSSQL15\sqlservr.exe", "2019.150.2000.5"),
                   ("TCP", "0.0.0.0", 8080, 3344, "tomcat9.exe", r"C:\Program Files\Apache\Tomcat 9.0\bin\tomcat9.exe", "9.0.96"),
                   ("TCP", "0.0.0.0", 3389, 1240, "svchost.exe", r"C:\Windows\System32\svchost.exe", "10.0.20348.1")],
}

COMMON_PROCESSES = [
    ("System", 4, None, None), ("Registry", 352, None, None), ("smss.exe", 1108, r"C:\Windows\System32\smss.exe", "10.0.26100.1"),
    ("csrss.exe", 1524, r"C:\Windows\System32\csrss.exe", "10.0.26100.1"), ("wininit.exe", 1652, r"C:\Windows\System32\wininit.exe", "10.0.26100.1"),
    ("services.exe", 1768, r"C:\Windows\System32\services.exe", "10.0.26100.1"), ("lsass.exe", 1824, r"C:\Windows\System32\lsass.exe", "10.0.26100.1"),
    ("svchost.exe", 1160, r"C:\Windows\System32\svchost.exe", "10.0.26100.1"), ("svchost.exe", 2264, r"C:\Windows\System32\svchost.exe", "10.0.26100.1"),
    ("explorer.exe", 6120, r"C:\Windows\explorer.exe", "10.0.26100.1"), ("CSFalconService.exe", 5020, r"C:\Program Files\CrowdStrike\CSFalconService.exe", "7.19.18913.0"),
]

COMMON_SERVICES = [
    ("Spooler", "Print Spooler", "Running", "Auto"), ("WinRM", "Windows Remote Management (WS-Management)", "Running", "Auto"),
    ("LanmanServer", "Server", "Running", "Auto"), ("wuauserv", "Windows Update", "Running", "Manual"),
    ("CSFalconService", "CrowdStrike Falcon Sensor Service", "Running", "Auto"), ("RemoteRegistry", "Remote Registry", "Stopped", "Disabled"),
    ("BITS", "Background Intelligent Transfer Service", "Running", "Manual"), ("Dnscache", "DNS Client", "Running", "Auto"),
]

EXTRA_SERVICES = {
    "FIN-LAPTOP-042": [("TermService", "Remote Desktop Services", "Running", "Manual")],
    "DEV-WS-017": [("postgresql-x64-16", "postgresql-x64-16 - PostgreSQL Server 16", "Running", "Auto")],
    "SRV-APP-03": [("MSSQLSERVER", "SQL Server (MSSQLSERVER)", "Running", "Auto"), ("Tomcat9", "Apache Tomcat 9.0 Tomcat9", "Running", "Auto"),
                   ("TermService", "Remote Desktop Services", "Running", "Manual")],
}


def inventory_for(machine: dict, *, drift: bool = False) -> dict:
    """Full inventory dict for one machine. drift=True randomly bumps a version / toggles a port."""
    h = machine["hostname"]
    software = [{"name": n, "version": v, "publisher": p} for n, v, p in COMMON_SOFTWARE + EXTRA_SOFTWARE.get(h, [])]
    ports = [dict(zip(("protocol", "local_address", "port", "pid", "process_name", "path", "version"), row))
             for row in COMMON_PORTS + EXTRA_PORTS.get(h, [])]
    processes = [dict(zip(("name", "pid", "path", "version"), row)) for row in COMMON_PROCESSES]
    services = [dict(zip(("name", "display_name", "status", "start_type"), row)) for row in COMMON_SERVICES + EXTRA_SERVICES.get(h, [])]

    if drift:
        sw = random.choice(software)
        parts = sw["version"].split(".")
        if parts[-1].isdigit():
            parts[-1] = str(int(parts[-1]) + random.randint(1, 5))
            sw["version"] = ".".join(parts)
        if random.random() < 0.4:
            ports.append({"protocol": "TCP", "local_address": "0.0.0.0", "port": random.choice([8443, 9000, 5000]),
                          "pid": random.randint(9000, 20000), "process_name": "java.exe",
                          "path": r"C:\Program Files\Java\jre\bin\java.exe", "version": "21.0.5"})
        for p in processes:
            if p["pid"] > 1000:
                p["pid"] += random.randint(1, 50) * 4

    return {
        "machine": {"id": machine["id"], "hostname": h, "os": machine["os"]},
        "installed_software": software,
        "listening_ports": ports,
        "processes": processes,
        "services": services,
    }


def random_machine(i: int) -> dict:
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"fake-pc-{i}")), "hostname": f"FAKE-PC-{i:03d}",
            "os": random.choice(["Windows 11 Enterprise 10.0.26100", "Windows 10 Pro 10.0.19045"])}
