import { useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router'
import {
  Alert, Box, Breadcrumbs, Card, CardContent, FormControl, InputLabel, Link, MenuItem, Paper, Select, Stack, Tab, Tabs,
  Typography,
} from '@mui/material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import {
  type PortRow, type ProcessRow, type Section, type ServiceRow, type SoftwareRow, useMachine, useMachineSection,
  useMachineSnapshots,
} from '../api'
import { ErrorBox, ExposedChip, Loading, OnlineChip, SourceChip } from '../components/common'
import { fmtDate, sourceLabel, timeAgo } from '../format'

const COLUMNS: Record<Section, GridColDef[]> = {
  software: [
    { field: 'name', headerName: 'Name', flex: 1.5, minWidth: 220 },
    { field: 'version', headerName: 'Version', flex: 0.7, minWidth: 120 },
    { field: 'publisher', headerName: 'Publisher', flex: 1, minWidth: 160 },
  ],
  ports: [
    { field: 'protocol', headerName: 'Protocol', width: 95 },
    { field: 'port', headerName: 'Port', type: 'number', width: 90 },
    { field: 'local_address', headerName: 'Address', width: 140 },
    { field: 'exposed', headerName: 'Exposure', width: 120, renderCell: (p) => <ExposedChip exposed={(p.row as PortRow).exposed} /> },
    { field: 'process_name', headerName: 'Application', flex: 0.8, minWidth: 150 },
    { field: 'pid', headerName: 'PID', type: 'number', width: 80 },
    { field: 'version', headerName: 'Version', width: 130 },
    { field: 'path', headerName: 'Path', flex: 1.4, minWidth: 220 },
  ],
  processes: [
    { field: 'name', headerName: 'Name', flex: 1, minWidth: 180 },
    { field: 'pid', headerName: 'PID', type: 'number', width: 90 },
    { field: 'version', headerName: 'Version', width: 140 },
    { field: 'path', headerName: 'Path', flex: 1.6, minWidth: 260 },
  ],
  services: [
    { field: 'name', headerName: 'Name', flex: 0.8, minWidth: 160 },
    { field: 'display_name', headerName: 'Display name', flex: 1.4, minWidth: 220 },
    { field: 'status', headerName: 'Status', width: 110 },
    { field: 'start_type', headerName: 'Start type', width: 110 },
  ],
}

const LABELS: Record<Section, string> = { software: 'Software', ports: 'Ports', processes: 'Processes', services: 'Services' }

function SectionGrid({ machineId, section, snapshotId }: { machineId: string; section: Section; snapshotId: string }) {
  const { data, isLoading, error } = useMachineSection<SoftwareRow | PortRow | ProcessRow | ServiceRow>(machineId, section, snapshotId)
  if (error) return <ErrorBox error={error} />
  const snap = data?.snapshot
  return (
    <>
      {!isLoading && !snap && <Alert severity="info" sx={{ mb: 1 }}>No {LABELS[section].toLowerCase()} data received for this machine yet.</Alert>}
      {snap && !data?.included && (
        <Alert severity="info" sx={{ mb: 1 }}>This snapshot did not include {LABELS[section].toLowerCase()}.</Alert>
      )}
      {snap && data?.included && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          From snapshot collected {fmtDate(snap.collected_at)} ({sourceLabel(snap.source)}{snap.filename ? `: ${snap.filename}` : ''})
        </Typography>
      )}
      <Paper sx={{ height: 'calc(100vh - 400px)', minHeight: 360 }}>
        <DataGrid
          rows={data?.items ?? []}
          columns={COLUMNS[section]}
          loading={isLoading}
          showToolbar
          density="compact"
          disableRowSelectionOnClick
          initialState={{ pagination: { paginationModel: { pageSize: 100 } } }}
          pageSizeOptions={[50, 100, 250]}
          getRowClassName={(p) => (section === 'ports' && (p.row as PortRow).exposed ? 'row-exposed' : '')}
          sx={{ border: 0, '& .row-exposed': { bgcolor: (t) => t.palette.mode === 'light' ? '#fff8e1' : 'rgba(255,167,38,0.12)' } }}
        />
      </Paper>
    </>
  )
}

export default function MachineDetail() {
  const { id = '' } = useParams()
  const machine = useMachine(id)
  const snapshots = useMachineSnapshots(id)
  const [tab, setTab] = useState<Section>('software')
  const [snapshotId, setSnapshotId] = useState('')  // '' = current (latest per section)

  if (machine.isLoading) return <Loading />
  if (machine.error || !machine.data) return <ErrorBox error={machine.error ?? 'Machine not found'} />
  const m = machine.data

  return (
    <>
      <Breadcrumbs sx={{ mb: 1 }}>
        <Link component={RouterLink} to="/machines" underline="hover">Machines</Link>
        <Typography color="text.primary">{m.hostname ?? m.id}</Typography>
      </Breadcrumbs>

      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ justifyContent: 'space-between', alignItems: { md: 'center' } }}>
            <Box>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                <Typography variant="h5" sx={{ fontWeight: 600 }}>{m.hostname ?? 'Unnamed machine'}</Typography>
                <OnlineChip online={m.online} />
              </Stack>
              <Typography variant="body2" color="text.secondary">{m.os ?? 'Unknown OS'}</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>{m.id}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                Last seen {timeAgo(m.last_seen)} · first seen {fmtDate(m.first_seen)} · {m.snapshot_count} snapshots
              </Typography>
              {m.extra && Object.keys(m.extra).length > 0 && (
                <Typography variant="body2" color="text.secondary">
                  {Object.entries(m.extra).map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}
                </Typography>
              )}
            </Box>
            <FormControl size="small" sx={{ minWidth: 320 }}>
              <InputLabel id="snap-label">Snapshot</InputLabel>
              <Select labelId="snap-label" label="Snapshot" value={snapshotId} onChange={(e) => setSnapshotId(e.target.value)}>
                <MenuItem value="">Current (latest data per section)</MenuItem>
                {(snapshots.data?.items ?? []).map((s) => (
                  <MenuItem key={s.id} value={s.id}>
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', width: '100%' }}>
                      <span>{fmtDate(s.collected_at)}</span>
                      <Box sx={{ flexGrow: 1 }} />
                      <SourceChip source={s.source} />
                    </Stack>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>
        </CardContent>
      </Card>

      <Tabs value={tab} onChange={(_, v: Section) => setTab(v)} sx={{ mb: 1 }} variant="scrollable" allowScrollButtonsMobile>
        {(Object.keys(LABELS) as Section[]).map((s) => <Tab key={s} value={s} label={LABELS[s]} />)}
      </Tabs>
      <SectionGrid machineId={id} section={tab} snapshotId={snapshotId} />
    </>
  )
}
