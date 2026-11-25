import { useMemo, useState } from 'react'
import { FormControlLabel, Paper, Switch } from '@mui/material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import { type FleetPort, type MachineRef, useFleetPorts } from '../api'
import { ErrorBox, ExposedChip, PageHeader } from '../components/common'
import MachinesDialog from '../components/MachinesDialog'

const columns: GridColDef<FleetPort>[] = [
  { field: 'protocol', headerName: 'Protocol', width: 100 },
  { field: 'port', headerName: 'Port', type: 'number', width: 100 },
  { field: 'process_name', headerName: 'Application', flex: 1, minWidth: 200 },
  { field: 'exposed', headerName: 'Exposure', width: 130, renderCell: (p) => <ExposedChip exposed={p.row.exposed} /> },
  { field: 'machine_count', headerName: 'Machines', type: 'number', width: 110 },
]

export default function Ports() {
  const { data, isLoading, error } = useFleetPorts()
  const [exposedOnly, setExposedOnly] = useState(false)
  const [selected, setSelected] = useState<{ title: string; machines: MachineRef[] } | null>(null)
  const rows = useMemo(() => (data?.items ?? []).filter((r) => !exposedOnly || r.exposed), [data, exposedOnly])
  if (error) return <ErrorBox error={error} />
  return (
    <>
      <PageHeader
        title="Ports"
        subtitle="Listening ports across all machines (current state). Exposed = listening on a non-loopback address."
        action={<FormControlLabel control={<Switch checked={exposedOnly} onChange={(e) => setExposedOnly(e.target.checked)} />} label="Exposed only" />}
      />
      <Paper sx={{ height: 'calc(100vh - 220px)', minHeight: 400 }}>
        <DataGrid
          rows={rows}
          columns={columns}
          getRowId={(r) => `${r.protocol}|${r.port}|${r.process_name ?? ''}`}
          loading={isLoading}
          showToolbar
          density="compact"
          disableRowSelectionOnClick
          onRowClick={(p) => setSelected({ title: `${p.row.protocol ?? ''} ${p.row.port} · ${p.row.process_name ?? 'unknown'}`, machines: p.row.machines })}
          initialState={{ pagination: { paginationModel: { pageSize: 100 } } }}
          pageSizeOptions={[50, 100, 250]}
          sx={{ border: 0, '& .MuiDataGrid-row': { cursor: 'pointer' } }}
        />
      </Paper>
      <MachinesDialog title={selected?.title ?? ''} machines={selected?.machines ?? null} onClose={() => setSelected(null)} />
    </>
  )
}
