import axios from 'axios'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

// indexes: null sends arrays as ?a=1&a=2 (what FastAPI expects), not ?a[]=1&a[]=2
export const http = axios.create({ baseURL: '/api/v1', paramsSerializer: { indexes: null } })

// ---------- types (mirror backend/app/routers/read.py) ----------
export type Section = 'software' | 'ports' | 'processes' | 'services'

export interface Snapshot {
  id: string
  machine_id: string
  hostname?: string
  source: string
  filename: string | null
  collected_at: string
  received_at: string
  software_count: number | null
  port_count: number | null
  process_count: number | null
  service_count: number | null
  extra: Record<string, unknown> | null
}

export interface Machine {
  id: string
  hostname: string | null
  os: string | null
  first_seen: string
  last_seen: string | null
  extra: Record<string, unknown> | null
  online: boolean
  snapshot_count: number
  software_count?: number | null
  port_count?: number | null
  process_count?: number | null
  service_count?: number | null
}

export interface Stats {
  machines: number
  online: number
  online_minutes: number
  period_hours: number
  snapshots_recent: number
  unique_apps: number
  exposed_ports: number
  top_software: { name: string; publisher: string | null; machine_count: number }[]
  top_ports: { protocol: string | null; port: number; machine_count: number; exposed: boolean }[]
  recent_snapshots: Snapshot[]
}

/** Dashboard filters (query parameters of GET /stats). Empty = no filter. */
export interface StatsFilters {
  machine_id: string[]
  os: string
  status: '' | 'online' | 'offline'
  hours: number
}

export interface SectionResponse<T> {
  snapshot: Snapshot | null
  included: boolean
  items: T[]
}

export interface SoftwareRow { id: number; name: string; version: string | null; publisher: string | null; extra: unknown }
export interface PortRow {
  id: number; protocol: string | null; local_address: string | null; port: number; pid: number | null
  process_name: string | null; path: string | null; version: string | null; exposed: boolean; extra: unknown
}
export interface ProcessRow { id: number; name: string; pid: number | null; path: string | null; version: string | null; extra: unknown }
export interface ServiceRow {
  id: number; name: string; display_name: string | null; status: string | null; start_type: string | null; extra: unknown
}

export interface MachineRef { id: string; hostname: string | null; local_address?: string | null; version?: string | null }
export interface FleetSoftware { name: string; publisher: string | null; version: string | null; machine_count: number; machines: MachineRef[] }
export interface FleetPort {
  protocol: string | null; port: number; process_name: string | null; machine_count: number; exposed: boolean; machines: MachineRef[]
}

// ---------- threat intelligence (mirror backend/app/routers/threat.py) ----------
export type VulnStatus = 'vulnerable' | 'review' | 'ruled_out'
export interface PortRef { protocol: string | null; port: number; exposed: boolean }
export interface Vulnerability {
  machine_id: string; hostname: string | null
  software_name: string; software_version: string | null; publisher: string | null
  cve_id: string; status: VulnStatus; reason: string | null; risk: number
  severity: string | null; cvss_v3: number | null; epss: number | null
  is_cisa_kev: boolean; has_public_poc: boolean; has_metasploit: boolean; has_nuclei: boolean
  vulnerable_range: string | null; fixed_version: string | null
  matched_vendor: string | null; matched_product: string | null; ai_summary: string | null
  exposed: boolean; ports: PortRef[]
}
export interface VulnFilters {
  status: 'actionable' | VulnStatus | 'all'
  kev_only: boolean
  exploit_only: boolean
  q: string
}
export interface VulnSummary {
  findings: number; machines: number; applications: number; cves: number
  vulnerable: number; review: number; kev: number; exploit: number
  by_severity: Record<string, number>
  top_cves: { cve_id: string; severity: string | null; cvss_v3: number | null; is_cisa_kev: boolean; risk: number; machines: number; software: string }[]
}
export interface ThreatStatus {
  enabled: boolean; ati_url: string | null; poll_minutes: number; max_range_lookups: number
  cached_ranges: number; stored_findings: number
  running: boolean; last_run: string | null; last_error: string | null
  last_result: { applications: number; candidate_cves: number; lookups: number; lookup_errors: number; lookups_pending: number
                 vulnerable: number; review: number; ruled_out: number } | null
}

export interface UploadResult {
  filename: string
  snapshots: { snapshot_id: string; machine_id: string; hostname: string | null; collected_at: string; counts: Record<string, number | null> }[]
}
export interface UploadError { sheet: string | null; row: number | null; error: string }

// ---------- hooks ----------
const get = async <T,>(url: string, params?: object) => (await http.get<T>(url, { params })).data

export const useStats = (f: StatsFilters) =>
  useQuery({
    queryKey: ['stats', f],
    queryFn: () => get<Stats>('/stats', {
      machine_id: f.machine_id.length ? f.machine_id : undefined,
      os: f.os || undefined,
      status: f.status || undefined,
      hours: f.hours,
    }),
    placeholderData: keepPreviousData, // keep the page while new filter results load
  })

export const useMachines = () =>
  useQuery({ queryKey: ['machines'], queryFn: () => get<{ total: number; items: Machine[] }>('/machines', { limit: 5000 }) })

export const useMachine = (id: string) =>
  useQuery({ queryKey: ['machine', id], queryFn: () => get<Machine>(`/machines/${id}`) })

export const useMachineSnapshots = (id: string) =>
  useQuery({ queryKey: ['machine-snapshots', id], queryFn: () => get<{ items: Snapshot[] }>(`/machines/${id}/snapshots`) })

export const useMachineSection = <T,>(id: string, section: Section, snapshotId: string) =>
  useQuery({
    queryKey: ['machine-section', id, section, snapshotId],
    queryFn: () => get<SectionResponse<T>>(`/machines/${id}/${section}`, snapshotId ? { snapshot_id: snapshotId } : undefined),
  })

export const useSnapshots = () =>
  useQuery({ queryKey: ['snapshots'], queryFn: () => get<{ items: Snapshot[] }>('/snapshots', { limit: 2000 }) })

export const useFleetSoftware = () =>
  useQuery({ queryKey: ['fleet-software'], queryFn: () => get<{ items: FleetSoftware[] }>('/software') })

export const useFleetPorts = () =>
  useQuery({ queryKey: ['fleet-ports'], queryFn: () => get<{ items: FleetPort[] }>('/ports') })

export const useVulnerabilities = (f: VulnFilters) =>
  useQuery({
    queryKey: ['vulnerabilities', f],
    queryFn: () => get<{ total: number; items: Vulnerability[] }>('/vulnerabilities', {
      status: f.status, kev_only: f.kev_only || undefined, exploit_only: f.exploit_only || undefined,
      q: f.q || undefined, limit: 10000,
    }),
    placeholderData: keepPreviousData,
  })

export const useVulnSummary = () =>
  useQuery({ queryKey: ['vulnerability-summary'], queryFn: () => get<VulnSummary>('/vulnerabilities/summary') })

/** Polls faster while a scan is running. */
export const useThreatStatus = () =>
  useQuery({
    queryKey: ['threat-status'],
    queryFn: () => get<ThreatStatus>('/vulnerabilities/status'),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : 30000),
  })

export const startThreatScan = async () => (await http.post('/vulnerabilities/scan')).data
