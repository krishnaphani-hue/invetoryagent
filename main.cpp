// Windows Inventory Agent - C++17, Win32 API, UTF-8 everywhere.
// Wide (UTF-16) Win32 calls internally; every string leaving the process
// (database, log, buffer files, config) is UTF-8.
#ifndef UNICODE
#define UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <iphlpapi.h>
#include <windows.h>
#include <shellapi.h>
#include <tlhelp32.h>
#include <libpq-fe.h>

#include <algorithm>
#include <cstdio>
#include <map>
#include <set>
#include <string>
#include <vector>

static const wchar_t* kServiceName = L"InventoryAgent";

// ---------- UTF-8 helpers ----------
static std::string U8(const std::wstring& w) {
    if (w.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string s(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), s.data(), n, nullptr, nullptr);
    return s;
}
static std::wstring W(const std::string& s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0);
    std::wstring w(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), w.data(), n);
    return w;
}

// ---------- paths, config, log ----------
static std::wstring DataDir() {
    wchar_t buf[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"ProgramData", buf, MAX_PATH);
    std::wstring d = n ? std::wstring(buf, n) : L"C:\\ProgramData";
    d += L"\\InventoryAgent";
    CreateDirectoryW(d.c_str(), nullptr);
    return d;
}
static std::wstring ExeDir() {
    wchar_t buf[MAX_PATH];
    DWORD n = GetModuleFileNameW(nullptr, buf, MAX_PATH);
    std::wstring p(buf, n);
    return p.substr(0, p.find_last_of(L'\\'));
}

static std::string ReadFileUtf8(const std::wstring& path) {
    HANDLE h = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) return {};
    LARGE_INTEGER sz{};
    GetFileSizeEx(h, &sz);
    std::string s((size_t)sz.QuadPart, '\0');
    DWORD got = 0;
    ReadFile(h, s.data(), (DWORD)s.size(), &got, nullptr);
    CloseHandle(h);
    s.resize(got);
    if (s.size() >= 3 && (unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB && (unsigned char)s[2] == 0xBF)
        s.erase(0, 3);  // strip BOM
    return s;
}
static bool WriteFileUtf8(const std::wstring& path, const std::string& data, bool append = false) {
    HANDLE h = CreateFileW(path.c_str(), append ? FILE_APPEND_DATA : GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                           append ? OPEN_ALWAYS : CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD put = 0;
    bool ok = WriteFile(h, data.data(), (DWORD)data.size(), &put, nullptr) && put == data.size();
    CloseHandle(h);
    return ok;
}

static std::string Now() {
    SYSTEMTIME t;
    GetSystemTime(&t);
    char b[40];
    snprintf(b, sizeof b, "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute,
             t.wSecond, t.wMilliseconds);
    return b;
}

static bool gConsole = false;
static void Log(const std::string& level, const std::string& msg) {
    std::string line = Now() + " [" + level + "] " + msg + "\r\n";
    if (gConsole) fputs(line.c_str(), stdout), fflush(stdout);
    WriteFileUtf8(DataDir() + L"\\agent.log", line, true);
}

struct Config {
    std::string connInfo = "host=localhost port=5432 dbname=inventory user=agent password=change_me client_encoding=UTF8";
    int intervalMinutes = 5;
    bool collectSoftware = true;
    std::wstring bufferDir;
};
static std::string Trim(std::string s) {
    auto sp = [](unsigned char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; };
    while (!s.empty() && sp(s.back())) s.pop_back();
    size_t i = 0;
    while (i < s.size() && sp(s[i])) ++i;
    return s.substr(i);
}
static Config LoadConfig() {
    Config c;
    c.bufferDir = DataDir() + L"\\buffer";
    std::string txt = ReadFileUtf8(ExeDir() + L"\\config.ini");
    size_t pos = 0;
    while (pos < txt.size()) {
        size_t e = txt.find('\n', pos);
        std::string line = Trim(txt.substr(pos, e == std::string::npos ? std::string::npos : e - pos));
        pos = e == std::string::npos ? txt.size() : e + 1;
        if (line.empty() || line[0] == '#' || line[0] == ';') continue;
        size_t eq = line.find('=');
        if (eq == std::string::npos) continue;
        std::string k = Trim(line.substr(0, eq)), v = Trim(line.substr(eq + 1));
        if (k == "ConnectionString") c.connInfo = v;
        else if (k == "IntervalMinutes") c.intervalMinutes = std::max(1, atoi(v.c_str()));
        else if (k == "CollectInstalledSoftware") c.collectSoftware = (v == "1" || v == "true");
        else if (k == "BufferDirectory") c.bufferDir = W(v);
    }
    CreateDirectoryW(c.bufferDir.c_str(), nullptr);
    return c;
}

// ---------- data model ----------
struct Svc { std::wstring name, display, status, start; };
struct Proc { std::wstring name; DWORD pid; std::wstring path; std::wstring version; };
struct Port { std::wstring protocol, address; unsigned port; DWORD pid; std::wstring name, path, version; };

// File/product version of an executable (cached per path). Empty if unavailable.
static std::wstring VersionOf(const std::wstring& path) {
    static std::map<std::wstring, std::wstring> cache;
    if (path.empty()) return {};
    if (auto it = cache.find(path); it != cache.end()) return it->second;
    std::wstring ver;
    DWORD h = 0, sz = GetFileVersionInfoSizeW(path.c_str(), &h);
    if (sz) {
        std::vector<BYTE> data(sz);
        if (GetFileVersionInfoW(path.c_str(), 0, sz, data.data())) {
            struct LT { WORD lang, cp; }* tr = nullptr;
            UINT n = 0;
            if (VerQueryValueW(data.data(), L"\\VarFileInfo\\Translation", (LPVOID*)&tr, &n) && n >= sizeof(LT)) {
                wchar_t q[64];
                swprintf(q, 64, L"\\StringFileInfo\\%04x%04x\\ProductVersion", tr->lang, tr->cp);
                wchar_t* v = nullptr;
                if (VerQueryValueW(data.data(), q, (LPVOID*)&v, &n) && v) ver = v;
            }
            if (ver.empty()) {
                VS_FIXEDFILEINFO* fi = nullptr;
                if (VerQueryValueW(data.data(), L"\\", (LPVOID*)&fi, &n) && fi) {
                    wchar_t b[64];
                    swprintf(b, 64, L"%u.%u.%u.%u", HIWORD(fi->dwProductVersionMS), LOWORD(fi->dwProductVersionMS),
                             HIWORD(fi->dwProductVersionLS), LOWORD(fi->dwProductVersionLS));
                    ver = b;
                }
            }
        }
    }
    cache[path] = ver;
    return ver;
}
struct Soft { std::wstring name, version, publisher; };

static std::wstring RegStr(HKEY k, const wchar_t* val) {
    DWORD type = 0, sz = 0;
    if (RegQueryValueExW(k, val, nullptr, &type, nullptr, &sz) != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ))
        return {};
    std::wstring s(sz / sizeof(wchar_t) + 1, L'\0');
    if (RegQueryValueExW(k, val, nullptr, nullptr, (LPBYTE)s.data(), &sz) != ERROR_SUCCESS) return {};
    s.resize(wcslen(s.c_str()));
    return s;
}

static std::wstring MachineGuid() {
    HKEY k;
    std::wstring g;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Cryptography", 0, KEY_READ | KEY_WOW64_64KEY, &k) == ERROR_SUCCESS) {
        g = RegStr(k, L"MachineGuid");
        RegCloseKey(k);
    }
    return g;
}
static std::wstring Hostname() {
    wchar_t b[256];
    DWORD n = 256;
    return GetComputerNameExW(ComputerNameDnsHostname, b, &n) ? std::wstring(b, n) : L"unknown";
}
static std::wstring OsString() {
    typedef LONG(WINAPI * RtlGetVersionFn)(OSVERSIONINFOW*);
    OSVERSIONINFOW v{sizeof v};
    auto fn = (RtlGetVersionFn)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion");
    if (fn) fn(&v);
    wchar_t b[96];
    swprintf(b, 96, L"Windows %lu.%lu build %lu", v.dwMajorVersion, v.dwMinorVersion, v.dwBuildNumber);
    return b;
}

static std::vector<Svc> CollectServices() {
    std::vector<Svc> out;
    SC_HANDLE scm = OpenSCManagerW(nullptr, nullptr, SC_MANAGER_ENUMERATE_SERVICE | SC_MANAGER_CONNECT);
    if (!scm) return out;
    DWORD need = 0, count = 0, resume = 0;
    EnumServicesStatusExW(scm, SC_ENUM_PROCESS_INFO, SERVICE_WIN32, SERVICE_STATE_ALL, nullptr, 0, &need, &count, &resume, nullptr);
    std::vector<BYTE> buf(need + 4096);
    resume = 0;
    if (EnumServicesStatusExW(scm, SC_ENUM_PROCESS_INFO, SERVICE_WIN32, SERVICE_STATE_ALL, buf.data(), (DWORD)buf.size(),
                              &need, &count, &resume, nullptr)) {
        auto* e = (ENUM_SERVICE_STATUS_PROCESSW*)buf.data();
        for (DWORD i = 0; i < count; ++i) {
            Svc s{e[i].lpServiceName, e[i].lpDisplayName, L"Unknown", L"Unknown"};
            switch (e[i].ServiceStatusProcess.dwCurrentState) {
                case SERVICE_STOPPED: s.status = L"Stopped"; break;
                case SERVICE_START_PENDING: s.status = L"StartPending"; break;
                case SERVICE_STOP_PENDING: s.status = L"StopPending"; break;
                case SERVICE_RUNNING: s.status = L"Running"; break;
                case SERVICE_CONTINUE_PENDING: s.status = L"ContinuePending"; break;
                case SERVICE_PAUSE_PENDING: s.status = L"PausePending"; break;
                case SERVICE_PAUSED: s.status = L"Paused"; break;
            }
            if (SC_HANDLE h = OpenServiceW(scm, e[i].lpServiceName, SERVICE_QUERY_CONFIG)) {
                DWORD n = 0;
                QueryServiceConfigW(h, nullptr, 0, &n);
                std::vector<BYTE> cb(n);
                if (n && QueryServiceConfigW(h, (LPQUERY_SERVICE_CONFIGW)cb.data(), n, &n)) {
                    switch (((LPQUERY_SERVICE_CONFIGW)cb.data())->dwStartType) {
                        case SERVICE_BOOT_START: s.start = L"Boot"; break;
                        case SERVICE_SYSTEM_START: s.start = L"System"; break;
                        case SERVICE_AUTO_START: s.start = L"Automatic"; break;
                        case SERVICE_DEMAND_START: s.start = L"Manual"; break;
                        case SERVICE_DISABLED: s.start = L"Disabled"; break;
                    }
                }
                CloseServiceHandle(h);
            }
            out.push_back(std::move(s));
        }
    }
    CloseServiceHandle(scm);
    return out;
}

static std::vector<Proc> CollectProcesses() {
    std::vector<Proc> out;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return out;
    PROCESSENTRY32W pe{sizeof pe};
    for (BOOL ok = Process32FirstW(snap, &pe); ok; ok = Process32NextW(snap, &pe)) {
        Proc p{pe.szExeFile, pe.th32ProcessID, L""};
        if (HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pe.th32ProcessID)) {
            wchar_t path[32768];
            DWORD n = 32768;
            if (QueryFullProcessImageNameW(h, 0, path, &n)) p.path.assign(path, n);  // protected: stays empty
            CloseHandle(h);
        }
        p.version = VersionOf(p.path);
        out.push_back(std::move(p));
    }
    CloseHandle(snap);
    return out;
}

// Listening TCP ports and bound UDP ports, joined to the owning process.
static std::vector<Port> CollectPorts(const std::vector<Proc>& procs) {
    std::map<DWORD, const Proc*> byPid;
    for (auto& p : procs) byPid[p.pid] = &p;
    std::vector<Port> out;
    auto add = [&](const wchar_t* proto, int family, const void* addr, DWORD portNet, DWORD pid) {
        wchar_t a[64] = L"";
        InetNtopW(family, (void*)addr, a, 64);
        Port r{proto, a, (unsigned)ntohs((u_short)portNet), pid, L"", L"", L""};
        if (auto it = byPid.find(pid); it != byPid.end()) {
            r.name = it->second->name;
            r.path = it->second->path;
            r.version = it->second->version;
        } else if (pid == 4) r.name = L"System";
        out.push_back(std::move(r));
    };
    auto fetch = [&](auto getTable, ULONG family, auto cls, auto body) {
        ULONG sz = 0;
        getTable(nullptr, &sz, TRUE, family, cls, 0);
        for (int tries = 0; tries < 3; ++tries) {
            std::vector<BYTE> buf(sz + 4096);
            sz = (ULONG)buf.size();
            if (getTable(buf.data(), &sz, TRUE, family, cls, 0) == NO_ERROR) { body(buf.data()); return; }
        }
    };
    fetch(GetExtendedTcpTable, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, [&](BYTE* b) {
        auto* t = (MIB_TCPTABLE_OWNER_PID*)b;
        for (DWORD i = 0; i < t->dwNumEntries; ++i)
            add(L"TCP", AF_INET, &t->table[i].dwLocalAddr, t->table[i].dwLocalPort, t->table[i].dwOwningPid);
    });
    fetch(GetExtendedTcpTable, AF_INET6, TCP_TABLE_OWNER_PID_LISTENER, [&](BYTE* b) {
        auto* t = (MIB_TCP6TABLE_OWNER_PID*)b;
        for (DWORD i = 0; i < t->dwNumEntries; ++i)
            add(L"TCP6", AF_INET6, t->table[i].ucLocalAddr, t->table[i].dwLocalPort, t->table[i].dwOwningPid);
    });
    fetch(GetExtendedUdpTable, AF_INET, UDP_TABLE_OWNER_PID, [&](BYTE* b) {
        auto* t = (MIB_UDPTABLE_OWNER_PID*)b;
        for (DWORD i = 0; i < t->dwNumEntries; ++i)
            add(L"UDP", AF_INET, &t->table[i].dwLocalAddr, t->table[i].dwLocalPort, t->table[i].dwOwningPid);
    });
    fetch(GetExtendedUdpTable, AF_INET6, UDP_TABLE_OWNER_PID, [&](BYTE* b) {
        auto* t = (MIB_UDP6TABLE_OWNER_PID*)b;
        for (DWORD i = 0; i < t->dwNumEntries; ++i)
            add(L"UDP6", AF_INET6, t->table[i].ucLocalAddr, t->table[i].dwLocalPort, t->table[i].dwOwningPid);
    });
    return out;
}

static std::vector<Soft> CollectSoftware() {
    std::map<std::wstring, Soft> uniq;
    const REGSAM views[] = {KEY_WOW64_64KEY, KEY_WOW64_32KEY};
    for (REGSAM view : views) {
        HKEY root;
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall", 0,
                          KEY_READ | view, &root) != ERROR_SUCCESS) continue;
        wchar_t name[256];
        for (DWORD i = 0;; ++i) {
            DWORD n = 256;
            if (RegEnumKeyExW(root, i, name, &n, nullptr, nullptr, nullptr, nullptr) != ERROR_SUCCESS) break;
            HKEY k;
            if (RegOpenKeyExW(root, name, 0, KEY_READ | view, &k) != ERROR_SUCCESS) continue;
            Soft s{RegStr(k, L"DisplayName"), RegStr(k, L"DisplayVersion"), RegStr(k, L"Publisher")};
            RegCloseKey(k);
            if (!s.name.empty()) uniq[s.name + L"|" + s.version] = s;
        }
        RegCloseKey(root);
    }
    std::vector<Soft> out;
    for (auto& kv : uniq) out.push_back(kv.second);
    return out;
}

// ---------- SQL building (UTF-8) ----------
static std::string Lit(const std::wstring& w) {  // quoted SQL literal, '' for empty -> NULL handled by caller
    std::string s = U8(w), o = "'";
    for (char c : s) {
        if (c == '\0') continue;
        if (c == '\'') o += '\'';
        o += c;
    }
    return o + "'";
}
static std::string LitOrNull(const std::wstring& w) { return w.empty() ? "NULL" : Lit(w); }

static std::string BuildScript(const std::wstring& id, const std::wstring& host, const std::wstring& os,
                               const std::vector<Svc>& svcs, const std::vector<Proc>& procs,
                               const std::vector<Soft>& soft, const std::vector<Port>& ports) {
    std::string ts = "'" + Now() + "'", mid = Lit(id) + "::uuid";
    std::string sql = "BEGIN;SET LOCAL standard_conforming_strings=on;\n";
    sql += "INSERT INTO machines(id,hostname,os,last_seen) VALUES(" + mid + "," + Lit(host) + "," + Lit(os) +
           ",now()) ON CONFLICT (id) DO UPDATE SET last_seen=now(),hostname=EXCLUDED.hostname,os=EXCLUDED.os;\n";
    auto batch = [&](const char* head, size_t total, auto rowFn) {
        for (size_t i = 0; i < total; i += 500) {
            sql += head;
            for (size_t j = i; j < std::min(total, i + 500); ++j) sql += (j > i ? "," : "") + rowFn(j);
            sql += ";\n";
        }
    };
    batch("INSERT INTO services(machine_id,name,display_name,status,start_type,collected_at) VALUES ", svcs.size(),
          [&](size_t j) { auto& s = svcs[j]; return "(" + mid + "," + Lit(s.name) + "," + Lit(s.display) + "," + Lit(s.status) + "," + Lit(s.start) + "," + ts + ")"; });
    batch("INSERT INTO processes(machine_id,name,pid,path,version,collected_at) VALUES ", procs.size(),
          [&](size_t j) { auto& p = procs[j]; return "(" + mid + "," + Lit(p.name) + "," + std::to_string(p.pid) + "," + LitOrNull(p.path) + "," + LitOrNull(p.version) + "," + ts + ")"; });
    batch("INSERT INTO listening_ports(machine_id,protocol,local_address,port,pid,process_name,path,version,collected_at) VALUES ", ports.size(),
          [&](size_t j) { auto& r = ports[j]; return "(" + mid + "," + Lit(r.protocol) + "," + Lit(r.address) + "," + std::to_string(r.port) + "," + std::to_string(r.pid) + "," + LitOrNull(r.name) + "," + LitOrNull(r.path) + "," + LitOrNull(r.version) + "," + ts + ")"; });
    batch("INSERT INTO installed_software(machine_id,name,version,publisher,collected_at) VALUES ", soft.size(),
          [&](size_t j) { auto& s = soft[j]; return "(" + mid + "," + Lit(s.name) + "," + LitOrNull(s.version) + "," + LitOrNull(s.publisher) + "," + ts + ")"; });
    sql += "COMMIT;";
    return sql;
}

// ---------- upload with retry + buffer ----------
static bool RunSql(const Config& cfg, const std::string& sql) {
    PGconn* c = PQconnectdb(cfg.connInfo.c_str());
    bool ok = false;
    if (PQstatus(c) == CONNECTION_OK) {
        PQsetClientEncoding(c, "UTF8");
        PGresult* r = PQexec(c, sql.c_str());
        ok = PQresultStatus(r) == PGRES_COMMAND_OK || PQresultStatus(r) == PGRES_TUPLES_OK;
        if (!ok) Log("WARN", std::string("SQL failed: ") + PQerrorMessage(c));
        PQclear(r);
    } else {
        Log("WARN", std::string("DB connect failed: ") + PQerrorMessage(c));
    }
    PQfinish(c);
    return ok;
}
static bool RunWithRetry(const Config& cfg, const std::string& sql, HANDLE stopEvt) {
    DWORD delayMs = 2000;
    for (int attempt = 1; attempt <= 4; ++attempt) {
        if (RunSql(cfg, sql)) return true;
        if (attempt == 4) break;
        if (WaitForSingleObject(stopEvt, delayMs) == WAIT_OBJECT_0) return false;
        delayMs *= 2;
    }
    return false;
}
static bool Upload(const Config& cfg, const std::string& sql, HANDLE stopEvt) {
    // flush older buffered scripts first, oldest first
    std::set<std::wstring> files;
    WIN32_FIND_DATAW fd;
    if (HANDLE h = FindFirstFileW((cfg.bufferDir + L"\\*.sql").c_str(), &fd); h != INVALID_HANDLE_VALUE) {
        do files.insert(fd.cFileName); while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    for (auto& f : files) {
        std::wstring full = cfg.bufferDir + L"\\" + f;
        std::string old = ReadFileUtf8(full);
        if (!old.empty() && !RunWithRetry(cfg, old, stopEvt)) goto buffer;
        DeleteFileW(full.c_str());
    }
    if (RunWithRetry(cfg, sql, stopEvt)) return true;
buffer:
    std::string name = Now();
    for (auto& ch : name) if (ch == ':' || ch == '.' || ch == '-') ch = '_';
    WriteFileUtf8(cfg.bufferDir + L"\\" + W(name) + L".sql", sql);
    Log("WARN", "DB unreachable; snapshot buffered");
    return false;
}

// ---------- main loop ----------
static void RunAgent(HANDLE stopEvt) {
    Config cfg = LoadConfig();
    std::wstring id = MachineGuid(), host = Hostname(), os = OsString();
    Log("INFO", "InventoryAgent started on " + U8(host) + ", interval " + std::to_string(cfg.intervalMinutes) + " min");
    do {
        try {
            auto svcs = CollectServices();
            auto procs = CollectProcesses();
            auto soft = cfg.collectSoftware ? CollectSoftware() : std::vector<Soft>{};
            auto ports = CollectPorts(procs);
            std::string sql = BuildScript(id, host, os, svcs, procs, soft, ports);
            if (Upload(cfg, sql, stopEvt))
                Log("INFO", "Uploaded " + std::to_string(svcs.size()) + " services, " + std::to_string(procs.size()) +
                                " processes, " + std::to_string(soft.size()) + " software items, " +
                                std::to_string(ports.size()) + " ports");
        } catch (const std::exception& e) {
            Log("ERROR", std::string("Cycle failed: ") + e.what());
        }
    } while (WaitForSingleObject(stopEvt, (DWORD)cfg.intervalMinutes * 60 * 1000) == WAIT_TIMEOUT);
    Log("INFO", "InventoryAgent stopped");
}

// ---------- Windows service plumbing ----------
static SERVICE_STATUS_HANDLE gStatusHandle;
static HANDLE gStopEvt;
static void SetState(DWORD state, DWORD accepted = 0) {
    SERVICE_STATUS st{SERVICE_WIN32_OWN_PROCESS, state, accepted, NO_ERROR, 0, 0, state == SERVICE_START_PENDING ? 3000u : 0u};
    SetServiceStatus(gStatusHandle, &st);
}
static DWORD WINAPI CtrlHandler(DWORD ctrl, DWORD, LPVOID, LPVOID) {
    if (ctrl == SERVICE_CONTROL_STOP || ctrl == SERVICE_CONTROL_SHUTDOWN) {
        SetState(SERVICE_STOP_PENDING);
        SetEvent(gStopEvt);
        return NO_ERROR;
    }
    return ctrl == SERVICE_CONTROL_INTERROGATE ? NO_ERROR : ERROR_CALL_NOT_IMPLEMENTED;
}
static void WINAPI ServiceMain(DWORD, LPWSTR*) {
    gStatusHandle = RegisterServiceCtrlHandlerExW(kServiceName, CtrlHandler, nullptr);
    if (!gStatusHandle) return;
    gStopEvt = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    SetState(SERVICE_START_PENDING);
    SetState(SERVICE_RUNNING, SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN);
    RunAgent(gStopEvt);
    SetState(SERVICE_STOPPED);
}
static BOOL WINAPI ConsoleCtrl(DWORD) { SetEvent(gStopEvt); return TRUE; }

// ---------- install / uninstall (shared by CLI and GUI) ----------
static const wchar_t* kInstallSubdir = L"\\InventoryAgent";

static bool IsElevated() {
    HANDLE tok;
    TOKEN_ELEVATION e{};
    DWORD n = 0;
    bool r = false;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &tok)) {
        r = GetTokenInformation(tok, TokenElevation, &e, sizeof e, &n) && e.TokenIsElevated;
        CloseHandle(tok);
    }
    return r;
}
static std::wstring InstallDir() {
    wchar_t b[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"ProgramFiles", b, MAX_PATH);
    return (n ? std::wstring(b, n) : std::wstring(L"C:\\Program Files")) + kInstallSubdir;
}
static std::wstring Err(const wchar_t* what) {
    return std::wstring(what) + L" (error " + std::to_wstring(GetLastError()) + L")";
}
static void StopAndWait(SC_HANDLE s) {
    SERVICE_STATUS st{};
    ControlService(s, SERVICE_CONTROL_STOP, &st);
    for (int i = 0; i < 30; ++i) {
        if (!QueryServiceStatus(s, &st) || st.dwCurrentState == SERVICE_STOPPED) break;
        Sleep(500);
    }
}
static bool CopyPayload(const std::wstring& dst, std::wstring& msg) {
    std::wstring src = ExeDir();
    if (_wcsicmp(src.c_str(), dst.c_str()) == 0) return true;
    CreateDirectoryW(dst.c_str(), nullptr);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((src + L"\\*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) { msg = Err(L"Cannot read installer folder"); return false; }
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        std::wstring n = fd.cFileName;
        auto ends = [&](const wchar_t* e) { size_t l = wcslen(e); return n.size() >= l && _wcsicmp(n.c_str() + n.size() - l, e) == 0; };
        if (ends(L".obj") || ends(L".pdb") || ends(L".log") || ends(L".sql")) continue;
        bool keepExisting = _wcsicmp(n.c_str(), L"config.ini") == 0;  // never overwrite user settings
        if (!CopyFileW((src + L"\\" + n).c_str(), (dst + L"\\" + n).c_str(), keepExisting) &&
            !(keepExisting && GetLastError() == ERROR_FILE_EXISTS)) {
            msg = Err((L"Cannot copy " + n).c_str());
            FindClose(h);
            return false;
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return true;
}
static bool DoInstall(std::wstring& msg) {
    SC_HANDLE scm = OpenSCManagerW(nullptr, nullptr, SC_MANAGER_ALL_ACCESS);
    if (!scm) { msg = Err(L"Administrator rights are required"); return false; }
    std::wstring dir = InstallDir(), bin = L"\"" + dir + L"\\InventoryAgent.exe\"";
    SC_HANDLE s = OpenServiceW(scm, kServiceName, SERVICE_ALL_ACCESS);
    if (s) StopAndWait(s);  // release the exe so it can be replaced
    if (!CopyPayload(dir, msg)) { if (s) CloseServiceHandle(s); CloseServiceHandle(scm); return false; }
    if (s) {
        ChangeServiceConfigW(s, SERVICE_NO_CHANGE, SERVICE_AUTO_START, SERVICE_NO_CHANGE, bin.c_str(), nullptr, nullptr, nullptr, nullptr, nullptr, nullptr);
    } else {
        s = CreateServiceW(scm, kServiceName, L"Inventory Agent", SERVICE_ALL_ACCESS, SERVICE_WIN32_OWN_PROCESS,
                           SERVICE_AUTO_START, SERVICE_ERROR_NORMAL, bin.c_str(), nullptr, nullptr, nullptr, nullptr, nullptr);
        if (!s) { msg = Err(L"CreateService failed"); CloseServiceHandle(scm); return false; }
    }
    SC_ACTION act{SC_ACTION_RESTART, 5000};
    SERVICE_FAILURE_ACTIONSW fa{86400, nullptr, nullptr, 1, &act};
    ChangeServiceConfig2W(s, SERVICE_CONFIG_FAILURE_ACTIONS, &fa);
    SERVICE_DESCRIPTIONW d{(LPWSTR)L"Collects services, processes, ports and installed software into PostgreSQL."};
    ChangeServiceConfig2W(s, SERVICE_CONFIG_DESCRIPTION, &d);
    bool started = StartServiceW(s, 0, nullptr) || GetLastError() == ERROR_SERVICE_ALREADY_RUNNING;
    msg = started ? L"Inventory Agent is installed and running.\n\nFiles: " + dir + L"\nSettings: " + dir + L"\\config.ini\nLog: " + DataDir() + L"\\agent.log"
                  : Err(L"Installed, but the service failed to start");
    CloseServiceHandle(s);
    CloseServiceHandle(scm);
    return started;
}
static bool DoUninstall(std::wstring& msg) {
    SC_HANDLE scm = OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT);
    SC_HANDLE s = scm ? OpenServiceW(scm, kServiceName, SERVICE_ALL_ACCESS) : nullptr;
    if (!s) { msg = Err(L"Service not found or administrator rights required"); if (scm) CloseServiceHandle(scm); return false; }
    StopAndWait(s);
    bool ok = DeleteService(s) != 0;
    msg = ok ? L"Inventory Agent service removed.\n\nCollected data in the database and files in " + InstallDir() + L" were left in place."
             : Err(L"DeleteService failed");
    CloseServiceHandle(s);
    CloseServiceHandle(scm);
    return ok;
}
static bool ServiceExists() {
    SC_HANDLE scm = OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT);
    SC_HANDLE s = scm ? OpenServiceW(scm, kServiceName, SERVICE_QUERY_STATUS) : nullptr;
    bool r = s != nullptr;
    if (s) CloseServiceHandle(s);
    if (scm) CloseServiceHandle(scm);
    return r;
}

// ---------- GUI setup (double-click) ----------
static int SetupGui() {
    if (!IsElevated()) {  // relaunch self with a UAC prompt
        wchar_t me[MAX_PATH];
        GetModuleFileNameW(nullptr, me, MAX_PATH);
        SHELLEXECUTEINFOW sei{sizeof sei};
        sei.lpVerb = L"runas";
        sei.lpFile = me;
        sei.lpParameters = L"--setup";
        sei.nShow = SW_SHOWNORMAL;
        if (!ShellExecuteExW(&sei)) {
            MessageBoxW(nullptr, L"Administrator rights are required to install the Inventory Agent service.",
                        L"Inventory Agent Setup", MB_ICONWARNING | MB_OK);
            return 1;
        }
        return 0;
    }
    std::wstring msg;
    if (ServiceExists()) {
        int r = MessageBoxW(nullptr,
            L"Inventory Agent is already installed.\n\nYes = Reinstall / update\nNo = Uninstall\nCancel = Close",
            L"Inventory Agent Setup", MB_ICONQUESTION | MB_YESNOCANCEL);
        if (r == IDYES) { bool ok = DoInstall(msg); MessageBoxW(nullptr, msg.c_str(), L"Inventory Agent Setup", ok ? MB_ICONINFORMATION : MB_ICONERROR); return ok ? 0 : 1; }
        if (r == IDNO) { bool ok = DoUninstall(msg); MessageBoxW(nullptr, msg.c_str(), L"Inventory Agent Setup", ok ? MB_ICONINFORMATION : MB_ICONERROR); return ok ? 0 : 1; }
        return 0;
    }
    int r = MessageBoxW(nullptr,
        (L"Install Inventory Agent as a Windows service?\n\nIt will start automatically at boot and report services, running "
         L"applications, ports and installed software to the PostgreSQL database set in config.ini.\n\nInstall location:\n" + InstallDir()).c_str(),
        L"Inventory Agent Setup", MB_ICONQUESTION | MB_OKCANCEL);
    if (r != IDOK) return 0;
    bool ok = DoInstall(msg);
    MessageBoxW(nullptr, msg.c_str(), L"Inventory Agent Setup", ok ? MB_ICONINFORMATION : MB_ICONERROR);
    return ok ? 0 : 1;
}

static void AttachParentConsole() {
    if (AttachConsole(ATTACH_PARENT_PROCESS)) {
        FILE* f;
        freopen_s(&f, "CONOUT$", "w", stdout);
        freopen_s(&f, "CONOUT$", "w", stderr);
    }
}

int wmain(int argc, wchar_t** argv) {
    if (argc > 1) {
        std::wstring a = argv[1];
        if (a == L"--setup") return SetupGui();
        AttachParentConsole();
        SetConsoleOutputCP(CP_UTF8);
        std::wstring msg;
        if (a == L"--install") { bool ok = DoInstall(msg); fputws((msg + L"\n").c_str(), ok ? stdout : stderr); return ok ? 0 : 1; }
        if (a == L"--uninstall") { bool ok = DoUninstall(msg); fputws((msg + L"\n").c_str(), ok ? stdout : stderr); return ok ? 0 : 1; }
        if (a == L"--console") {
            gConsole = true;
            gStopEvt = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            SetConsoleCtrlHandler(ConsoleCtrl, TRUE);
            RunAgent(gStopEvt);
            return 0;
        }
        fputs("Usage: InventoryAgent [--setup | --console | --install | --uninstall]\n", stderr);
        return 2;
    }
    SERVICE_TABLE_ENTRYW table[] = {{(LPWSTR)kServiceName, ServiceMain}, {nullptr, nullptr}};
    if (!StartServiceCtrlDispatcherW(table)) {
        if (GetLastError() == ERROR_FAILED_SERVICE_CONTROLLER_CONNECT) return SetupGui();  // launched by a user, not the SCM
        return 1;
    }
    return 0;
}