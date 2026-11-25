import { useDeferredValue, useEffect, useRef, useState } from 'react'
import { Link as RouterLink } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Chip, Dialog, DialogContent, DialogTitle, FormControlLabel, Link, MenuItem, Paper, Stack, Switch,
  TextField, Typography,
} from '@mui/material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import SecurityIcon from '@mui/icons-material/SecurityOutlined'
import ComputerIcon from '@mui/icons-material/ComputerOutlined'
import WarningIcon from '@mui/icons-material/GppMaybeOutlined'
import BugIcon from '@mui/icons-material/BugReportOutlined'
import RadarIcon from '@mui/icons-material/RadarOutlined'
import {
  startThreatScan, useThreatStatus, useVulnSummary, useVulnerabilities, type VulnFilters, type Vulnerability, type VulnStatus,
} from '../api'
import { CardGrid, ErrorBox, PageHeader, StatCard } from '../components/common'
import { timeAgo } from '../format'

type Color = 'error' | 'warning' | 'info' | 'default'
const severityColor = (s: string | null): Color =>
  ({ critical: 'error', high: 'warning', medium: 'info' } as Record<string, Color>)[(s ?? '').toLowerCase()] ?? 'default'
const riskColor = (r: number): Color => (r >= 80 ? 'error' : r >= 60 ? 'warning' : r >= 40 ? 'info' : 'default')
const STATUS: Record<VulnStatus, { label: string; color: 'error' | 'warning' | 'default'; variant: 'filled' | 'outlined' }> = {
  vulnerable: { label: 'Vulnerable', color: 'error', variant: 'filled' },
  review: { label: 'Needs review', color: 'warning', variant: 'outlined' },
  ruled_out: { label: 'Ruled out', color: 'default', variant: 'outlined' },
}
const hasExploit = (v: Vulnerability) => v.has_public_poc || v.has_metasploit || v.has_nuclei
const portsText = (v: Vulnerability) => v.ports.map((p) => `${p.protocol ?? ''} ${p.port}${p.exposed ? ' (exposed)' : ''}`).join(', ')

const columns: GridColDef<Vulnerability>[] = [
  { field: 'risk', headerName: 'Risk', type: 'number', width: 80,
    renderCell: (p) => <Chip size="small" color={riskColor(p.row.risk)} label={p.row.risk} /> },
  { field: 'cve_id', headerName: 'CVE', width: 150,
    renderCell: (p) => (
      <Link href={`https://nvd.nist.gov/vuln/detail/${p.row.cve_id}`} target="_blank" rel="noreferrer"
            onClick={(e) => e.stopPropagation()}>{p.row.cve_id}</Link>
    ) },
  { field: 'severity', headerName: 'Severity', width: 105,
    renderCell: (p) => p.row.severity ? <Chip size="small" variant="outlined" color={severityColor(p.row.severity)} label={p.row.severity} /> : null },
  { field: 'cvss_v3', headerName: 'CVSS', type: 'number', width: 80 },
  { field: 'epss', headerName: 'EPSS', type: 'number', width: 80,
    valueFormatter: (v: number | null) => (v == null ? '' : `${(v * 100).toFixed(1)}%`) },
  { field: 'flags', headerName: 'Threat', width: 170, sortable: false,
    renderCell: (p) => (
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', height: '100%' }}>
        {p.row.is_cisa_kev && <Chip size="small" color="error" label="KEV" title="CISA Known Exploited Vulnerability" />}
        {hasExploit(p.row) && <Chip size="small" color="warning" label="Exploit" title="Public exploit code exists" />}
      </Stack>
    ) },
  { field: 'hostname', headerName: 'Machine', width: 170,
    renderCell: (p) => (
      <Link component={RouterLink} to={`/machines/${p.row.machine_id}`} onClick={(e) => e.stopPropagation()}>
        {p.row.hostname ?? p.row.machine_id}
      </Link>
    ) },
  { field: 'software_name', headerName: 'Software', flex: 1, minWidth: 220 },
  { field: 'software_version', headerName: 'Installed', width: 130 },
  { field: 'fixed_version', headerName: 'Fixed in', width: 110 },
  { field: 'ports', headerName: 'Listening ports', width: 190, sortable: false, valueGetter: (_, row) => portsText(row),
    renderCell: (p) => (
      <Typography variant="body2" color={p.row.exposed ? 'warning.main' : 'text.primary'} noWrap title={portsText(p.row)}>
        {portsText(p.row)}
      </Typography>
    ) },
  { field: 'status', headerName: 'Status', width: 130,
    renderCell: (p) => <Chip size="small" {...STATUS[p.row.status]} label={STATUS[p.row.status].label} /> },
]

function Detail({ v, onClose }: { v: Vulnerability | null; onClose: () => void }) {
  return (
    <Dialog open={!!v} onClose={onClose} maxWidth="sm" fullWidth>
      {v && (
        <>
          <DialogTitle>
            {v.cve_id} <Chip size="small" sx={{ ml: 1 }} {...STATUS[v.status]} label={STATUS[v.status].label} />
          </DialogTitle>
          <DialogContent>
            <Stack spacing={1.5}>
              <Typography variant="body2">{v.reason}</Typography>
              <Typography variant="body2">
                <b>Machine:</b> {v.hostname} · <b>Software:</b> {v.software_name} {v.software_version ?? ''}
                {v.publisher ? ` (${v.publisher})` : ''}
              </Typography>
              <Typography variant="body2">
                <b>Matched ATI product:</b> {v.matched_vendor} / {v.matched_product}. Check this is really the installed
                application: matching is by name.
              </Typography>
              <Typography variant="body2">
                <b>Vulnerable range:</b> {v.vulnerable_range ?? 'unknown'} · <b>Fixed in:</b> {v.fixed_version ?? 'unknown'}
              </Typography>
              <Typography variant="body2">
                <b>Severity:</b> {v.severity ?? '—'} · <b>CVSS:</b> {v.cvss_v3 ?? '—'} · <b>EPSS:</b>{' '}
                {v.epss == null ? '—' : `${(v.epss * 100).toFixed(1)}%`} · <b>Risk:</b> {v.risk}/100
              </Typography>
              <Typography variant="body2">
                <b>Listening ports of this application:</b> {v.ports.length ? portsText(v) : 'none found'}
              </Typography>
              {v.ai_summary && <Typography variant="body2" color="text.secondary">{v.ai_summary}</Typography>}
              <Link href={`https://nvd.nist.gov/vuln/detail/${v.cve_id}`} target="_blank" rel="noreferrer">View on NVD</Link>
            </Stack>
          </DialogContent>
        </>
      )}
    </Dialog>
  )
}

export default function Vulnerabilities() {
  const qc = useQueryClient()
  const status = useThreatStatus()
  const summary = useVulnSummary()
  const [filters, setFilters] = useState<VulnFilters>({ status: 'actionable', kev_only: false, exploit_only: false, q: '' })
  const [search, setSearch] = useState('')
  const deferred = useDeferredValue(search)
  const { data, isLoading, error } = useVulnerabilities({ ...filters, q: deferred })
  const [selected, setSelected] = useState<Vulnerability | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)

  // when a scan finishes, reload the findings
  const wasRunning = useRef(false)
  const running = status.data?.running ?? false
  useEffect(() => {
    if (wasRunning.current && !running) {
      qc.invalidateQueries({ queryKey: ['vulnerabilities'] })
      qc.invalidateQueries({ queryKey: ['vulnerability-summary'] })
    }
    wasRunning.current = running
  }, [running, qc])

  const scan = async () => {
    setScanError(null)
    try {
      await startThreatScan()
      qc.invalidateQueries({ queryKey: ['threat-status'] })
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setScanError(msg ?? (e instanceof Error ? e.message : String(e)))
    }
  }

  if (error) return <ErrorBox error={error} />
  const st = status.data
  const s = summary.data
  const r = st?.last_result

  return (
    <>
      <PageHeader
        title="Vulnerabilities"
        subtitle="Installed software matched against CVEs from Advanced-Threat-Intelligence (current state of every machine)."
        action={
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            {st?.last_run && <Typography variant="caption" color="text.secondary">Last scan {timeAgo(st.last_run)}</Typography>}
            <Button variant="contained" startIcon={<RadarIcon />} disabled={!st?.enabled || running} onClick={scan}>
              {running ? 'Scanning…' : 'Scan now'}
            </Button>
          </Stack>
        }
      />

      {st && !st.enabled && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Threat intelligence is off. Start Advanced-Threat-Intelligence (<code>python main.py --gui --port 8001</code>) and set{' '}
          <code>ATI_URL=http://127.0.0.1:8001</code> in <code>.env</code>, then restart this server.
        </Alert>
      )}
      {scanError && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setScanError(null)}>{scanError}</Alert>}
      {st?.last_error && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          The last scan failed: {st.last_error}. Earlier findings are kept. Is ATI running at {st.ati_url}?
        </Alert>
      )}
      {st?.enabled && r && r.lookups_pending > 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          {r.lookups_pending} CVE version range{r.lookups_pending === 1 ? '' : 's'} not checked yet (at most {st.max_range_lookups} per
          scan, riskiest first). Those findings show as “Needs review” and settle on later scans.
        </Alert>
      )}

      <CardGrid min={190}>
        <StatCard label="Need action" value={s?.findings ?? '—'} hint={`${s?.cves ?? 0} CVEs in ${s?.applications ?? 0} applications`} icon={<SecurityIcon />} />
        <StatCard label="Vulnerable" value={s?.vulnerable ?? '—'} hint="version inside the vulnerable range" icon={<BugIcon />} />
        <StatCard label="Machines affected" value={s?.machines ?? '—'} icon={<ComputerIcon />} />
        <StatCard label="CISA KEV" value={s?.kev ?? '—'} hint="known to be exploited in the wild" icon={<WarningIcon />} />
        <StatCard label="Public exploit" value={s?.exploit ?? '—'} hint="exploit code is published" icon={<BugIcon />} />
      </CardGrid>

      <Paper sx={{ p: 2, my: 2 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: { md: 'center' } }}>
          <TextField select size="small" label="Show" value={filters.status} sx={{ minWidth: 190 }}
                     onChange={(e) => setFilters({ ...filters, status: e.target.value as VulnFilters['status'] })}>
            <MenuItem value="actionable">Need action</MenuItem>
            <MenuItem value="vulnerable">Vulnerable only</MenuItem>
            <MenuItem value="review">Needs review only</MenuItem>
            <MenuItem value="ruled_out">Ruled out</MenuItem>
            <MenuItem value="all">Everything</MenuItem>
          </TextField>
          <TextField size="small" label="Search CVE, software, machine" value={search} sx={{ minWidth: 260 }}
                     onChange={(e) => setSearch(e.target.value)} />
          <FormControlLabel control={<Switch checked={filters.kev_only} onChange={(e) => setFilters({ ...filters, kev_only: e.target.checked })} />} label="CISA KEV" />
          <FormControlLabel control={<Switch checked={filters.exploit_only} onChange={(e) => setFilters({ ...filters, exploit_only: e.target.checked })} />} label="Public exploit" />
        </Stack>
      </Paper>

      <Paper sx={{ height: 'calc(100vh - 420px)', minHeight: 400 }}>
        <DataGrid
          rows={data?.items ?? []}
          columns={columns}
          getRowId={(v) => `${v.machine_id}|${v.software_name}|${v.software_version}|${v.cve_id}`}
          loading={isLoading || status.isLoading}
          showToolbar
          density="compact"
          disableRowSelectionOnClick
          onRowClick={(p) => setSelected(p.row)}
          initialState={{ pagination: { paginationModel: { pageSize: 100 } } }}
          pageSizeOptions={[50, 100, 250]}
          slotProps={{ noRowsOverlay: {} }}
          sx={{ border: 0, '& .MuiDataGrid-row': { cursor: 'pointer' } }}
        />
      </Paper>
      <Box sx={{ mt: 1 }}>
        <Typography variant="caption" color="text.secondary">
          Risk (0–100) = CVSS × 5 + 30 if CISA KEV + 15 if a public exploit exists + EPSS × 15, capped at 100. “Vulnerable” means the installed
          version is inside an affected version range NVD lists for that product. Products are matched by name, so check the matched
          product (click a row) before acting.
        </Typography>
      </Box>
      <Detail v={selected} onClose={() => setSelected(null)} />
    </>
  )
}
