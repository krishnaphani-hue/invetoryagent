import { useState } from 'react'
import { Paper } from '@mui/material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import { type FleetSoftware, type MachineRef, useFleetSoftware } from '../api'
import { ErrorBox, PageHeader } from '../components/common'
import MachinesDialog from '../components/MachinesDialog'

const columns: GridColDef<FleetSoftware>[] = [
  { field: 'name', headerName: 'Name', flex: 1.5, minWidth: 240 },
  { field: 'version', headerName: 'Version', flex: 0.7, minWidth: 130 },
  { field: 'publisher', headerName: 'Publisher', flex: 1, minWidth: 180 },
  { field: 'machine_count', headerName: 'Machines', type: 'number', width: 110 },
]

export default function Software() {
  const { data, isLoading, error } = useFleetSoftware()
  const [selected, setSelected] = useState<{ title: string; machines: MachineRef[] } | null>(null)
  if (error) return <ErrorBox error={error} />
  return (
    <>
      <PageHeader title="Software" subtitle="Installed software across all machines (current state). Click a row to see which machines have it." />
      <Paper sx={{ height: 'calc(100vh - 220px)', minHeight: 400 }}>
        <DataGrid
          rows={data?.items ?? []}
          columns={columns}
          getRowId={(r) => `${r.name}|${r.publisher ?? ''}|${r.version ?? ''}`}
          loading={isLoading}
          showToolbar
          density="compact"
          disableRowSelectionOnClick
          onRowClick={(p) => setSelected({ title: `${p.row.name} ${p.row.version ?? ''}`.trim(), machines: p.row.machines })}
          initialState={{ pagination: { paginationModel: { pageSize: 100 } } }}
          pageSizeOptions={[50, 100, 250]}
          sx={{ border: 0, '& .MuiDataGrid-row': { cursor: 'pointer' } }}
        />
      </Paper>
      <MachinesDialog title={selected?.title ?? ''} machines={selected?.machines ?? null} onClose={() => setSelected(null)} />
    </>
  )
}
