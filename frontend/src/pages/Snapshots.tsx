import { useNavigate } from 'react-router'
import { Paper } from '@mui/material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import { type Snapshot, useSnapshots } from '../api'
import { ErrorBox, PageHeader, SourceChip } from '../components/common'
import { fmtDate } from '../format'

const columns: GridColDef<Snapshot>[] = [
  { field: 'received_at', headerName: 'Received', width: 190, valueFormatter: (v: string) => fmtDate(v) },
  { field: 'collected_at', headerName: 'Collected', width: 190, valueFormatter: (v: string) => fmtDate(v) },
  { field: 'hostname', headerName: 'Machine', flex: 1, minWidth: 160 },
  { field: 'source', headerName: 'Source', width: 140, renderCell: (p) => <SourceChip source={p.row.source} /> },
  { field: 'filename', headerName: 'File', flex: 1, minWidth: 160 },
  { field: 'software_count', headerName: 'Apps', type: 'number', width: 80 },
  { field: 'port_count', headerName: 'Ports', type: 'number', width: 80 },
  { field: 'process_count', headerName: 'Processes', type: 'number', width: 100 },
  { field: 'service_count', headerName: 'Services', type: 'number', width: 100 },
]

export default function Snapshots() {
  const { data, isLoading, error } = useSnapshots()
  const navigate = useNavigate()
  if (error) return <ErrorBox error={error} />
  return (
    <>
      <PageHeader title="Snapshots" subtitle="Every delivery received, from the collector or an Excel upload. Empty count = section not included." />
      <Paper sx={{ height: 'calc(100vh - 220px)', minHeight: 400 }}>
        <DataGrid
          rows={data?.items ?? []}
          columns={columns}
          loading={isLoading}
          showToolbar
          density="compact"
          disableRowSelectionOnClick
          onRowClick={(p) => navigate(`/machines/${p.row.machine_id}`)}
          initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
          pageSizeOptions={[25, 50, 100]}
          sx={{ border: 0, '& .MuiDataGrid-row': { cursor: 'pointer' } }}
        />
      </Paper>
    </>
  )
}
