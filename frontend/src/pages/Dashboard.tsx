import { useMemo } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router'
import {
  Autocomplete, Box, Button, Card, CardContent, Chip, LinearProgress, Link, List, ListItem, ListItemText, MenuItem, Paper,
  Stack, TextField, Typography,
} from '@mui/material'
import ComputerIcon from '@mui/icons-material/ComputerOutlined'
import WifiIcon from '@mui/icons-material/WifiTetheringOutlined'
import AppsIcon from '@mui/icons-material/AppsOutlined'
import WarningIcon from '@mui/icons-material/GppMaybeOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import ClearIcon from '@mui/icons-material/FilterAltOffOutlined'
import SecurityIcon from '@mui/icons-material/SecurityOutlined'
import { type StatsFilters, useMachines, useStats, useThreatStatus, useVulnSummary } from '../api'
import { CardGrid, ErrorBox, Loading, PageHeader, SourceChip, StatCard } from '../components/common'
import { timeAgo } from '../format'

const PERIODS = [
  { hours: 24, label: 'Last 24 hours', short: '24 h' },
  { hours: 24 * 7, label: 'Last 7 days', short: '7 days' },
  { hours: 24 * 30, label: 'Last 30 days', short: '30 days' },
]
const DEFAULT_HOURS = 24

/** Filters live in the URL (?machine=..&machine=..&os=..&status=..&hours=..), so refresh and shared links keep them. */
function useDashboardFilters(): [StatsFilters, (patch: Partial<StatsFilters>) => void] {
  const [params, setParams] = useSearchParams()
  const filters = useMemo<StatsFilters>(() => {
    const status = params.get('status')
    const hours = Number(params.get('hours'))
    return {
      machine_id: params.getAll('machine'),
      os: params.get('os') ?? '',
      status: status === 'online' || status === 'offline' ? status : '',
      hours: PERIODS.some((p) => p.hours === hours) ? hours : DEFAULT_HOURS,
    }
  }, [params])
  const update = (patch: Partial<StatsFilters>) => {
    const next = { ...filters, ...patch }
    const p = new URLSearchParams()
    next.machine_id.forEach((id) => p.append('machine', id))
    if (next.os) p.set('os', next.os)
    if (next.status) p.set('status', next.status)
    if (next.hours !== DEFAULT_HOURS) p.set('hours', String(next.hours))
    setParams(p, { replace: true })
  }
  return [filters, update]
}

const isFiltered = (f: StatsFilters) => f.machine_id.length > 0 || !!f.os || !!f.status || f.hours !== DEFAULT_HOURS

function FilterBar({ filters, onChange }: { filters: StatsFilters; onChange: (patch: Partial<StatsFilters>) => void }) {
  const { data } = useMachines()
  const machines = useMemo(() => data?.items ?? [], [data])
  const osList = useMemo(() => {
    const set = new Set(machines.map((m) => m.os).filter((o): o is string => !!o))
    if (filters.os) set.add(filters.os) // keep a value from the URL selectable
    return [...set].sort()
  }, [machines, filters.os])
  const selected = machines.filter((m) => filters.machine_id.includes(m.id))

  return (
    <Paper sx={{ p: 2, mb: 2 }}>
      <Box sx={{
        display: 'grid', gap: 2, alignItems: 'center',
        gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', lg: 'minmax(260px, 2fr) repeat(3, minmax(150px, 1fr)) auto' },
      }}>
        <Box sx={{ gridColumn: { sm: '1 / -1', lg: 'auto' } }}>
          <Autocomplete
            multiple size="small" limitTags={2}
            options={machines}
            value={selected}
            getOptionLabel={(m) => m.hostname ?? m.id}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            onChange={(_, v) => onChange({ machine_id: v.map((m) => m.id) })}
            renderInput={(p) => <TextField {...p} label="Machines" placeholder={selected.length ? '' : 'All machines'} />}
          />
        </Box>
        <TextField select size="small" label="OS" value={filters.os} onChange={(e) => onChange({ os: e.target.value })}>
          <MenuItem value="">All</MenuItem>
          {osList.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Status" value={filters.status}
                   onChange={(e) => onChange({ status: e.target.value as StatsFilters['status'] })}>
          <MenuItem value="">All</MenuItem>
          <MenuItem value="online">Online</MenuItem>
          <MenuItem value="offline">Offline</MenuItem>
        </TextField>
        <TextField select size="small" label="Snapshots period" value={filters.hours}
                   onChange={(e) => onChange({ hours: Number(e.target.value) })}>
          {PERIODS.map((p) => <MenuItem key={p.hours} value={p.hours}>{p.label}</MenuItem>)}
        </TextField>
        <Button startIcon={<ClearIcon />} disabled={!isFiltered(filters)}
                onClick={() => onChange({ machine_id: [], os: '', status: '', hours: DEFAULT_HOURS })}>
          Clear
        </Button>
      </Box>
    </Paper>
  )
}

export default function Dashboard() {
  const [filters, setFilters] = useDashboardFilters()
  const { data, isLoading, isFetching, error } = useStats(filters)
  const threat = useThreatStatus()
  const vulns = useVulnSummary()
  const filtered = isFiltered(filters)
  const period = PERIODS.find((p) => p.hours === filters.hours) ?? PERIODS[0]
  const empty = filtered ? 'Nothing matches the filters.' : 'No data yet.'

  const header = (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={filtered
          ? 'Current state of the machines that match the filters, from their latest snapshots.'
          : 'Current state of every machine, from its latest snapshot.'}
      />
      <FilterBar filters={filters} onChange={setFilters} />
      <LinearProgress sx={{ mb: 1, height: 2, visibility: isFetching && !isLoading ? 'visible' : 'hidden' }} />
    </>
  )
  if (isLoading) return <>{header}<Loading /></>
  if (error || !data) return <>{header}<ErrorBox error={error} /></>

  const maxSw = Math.max(1, ...data.top_software.map((s) => s.machine_count))
  const maxPort = Math.max(1, ...data.top_ports.map((p) => p.machine_count))

  return (
    <>
      {header}
      <CardGrid min={190}>
        <StatCard label="Machines" value={data.machines} icon={<ComputerIcon />} />
        <StatCard label="Online" value={data.online} hint={`seen in the last ${data.online_minutes} min`} icon={<WifiIcon />} />
        <StatCard label="Unique applications" value={data.unique_apps} icon={<AppsIcon />} />
        <StatCard label="Exposed ports" value={data.exposed_ports} hint="listening on a non-loopback address" icon={<WarningIcon />} />
        <StatCard label={`Snapshots (${period.short})`} value={data.snapshots_recent} icon={<HistoryIcon />} />
        {threat.data?.enabled && vulns.data && (
          <Link component={RouterLink} to="/vulnerabilities" underline="none" color="inherit">
            <StatCard label="Vulnerable software" value={vulns.data.vulnerable}
                      hint={`${vulns.data.machines} machines · ${vulns.data.kev} CISA KEV · all machines`} icon={<SecurityIcon />} />
          </Link>
        )}
      </CardGrid>

      <Box sx={{ display: 'grid', gap: 2, mt: 2, gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' } }}>
        <Card>
          <CardContent>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>Most installed software</Typography>
            {data.top_software.length === 0 && <Typography color="text.secondary">{empty}</Typography>}
            {data.top_software.map((s) => (
              <Box key={s.name} sx={{ mb: 1.5 }}>
                <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
                  <Typography variant="body2" noWrap title={s.name}>{s.name}</Typography>
                  <Typography variant="body2" color="text.secondary">{s.machine_count}</Typography>
                </Stack>
                <LinearProgress variant="determinate" value={(s.machine_count / maxSw) * 100} sx={{ height: 6, borderRadius: 3 }} />
              </Box>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>Most common open ports</Typography>
            {data.top_ports.length === 0 && <Typography color="text.secondary">{empty}</Typography>}
            {data.top_ports.map((p) => (
              <Box key={`${p.protocol}-${p.port}`} sx={{ mb: 1.5 }}>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', minWidth: 90 }}>{p.protocol} {p.port}</Typography>
                  {p.exposed && <Chip size="small" color="warning" label="Exposed" />}
                  <Box sx={{ flexGrow: 1 }} />
                  <Typography variant="body2" color="text.secondary">{p.machine_count}</Typography>
                </Stack>
                <LinearProgress variant="determinate" color={p.exposed ? 'warning' : 'primary'} value={(p.machine_count / maxPort) * 100}
                                sx={{ height: 6, borderRadius: 3 }} />
              </Box>
            ))}
          </CardContent>
        </Card>
      </Box>

      <Card sx={{ mt: 2 }}>
        <CardContent>
          <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Latest snapshots ({period.label.toLowerCase()})</Typography>
            <Link component={RouterLink} to="/snapshots">View all</Link>
          </Stack>
          {data.recent_snapshots.length === 0 && (
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              {filtered ? empty : (
                <>No data yet. Send data from the collector or <Link component={RouterLink} to="/upload">upload an Excel file</Link>.</>
              )}
            </Typography>
          )}
          <List dense>
            {data.recent_snapshots.map((s) => (
              <ListItem key={s.id} disableGutters secondaryAction={<SourceChip source={s.source} />}>
                <ListItemText
                  primary={<Link component={RouterLink} to={`/machines/${s.machine_id}`}>{s.hostname ?? s.machine_id}</Link>}
                  secondary={`${timeAgo(s.received_at)} · software ${s.software_count ?? '—'} · ports ${s.port_count ?? '—'}`}
                />
              </ListItem>
            ))}
          </List>
        </CardContent>
      </Card>
    </>
  )
}
