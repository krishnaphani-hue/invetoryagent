import { useNavigate } from 'react-router'
import { Paper } from '@mui/material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import { type Machine, useMachines } from '../api'
import { ErrorBox, OnlineChip, PageHeader } from '../components/common'
import { fmtDate, timeAgo } from '../format'

const columns: GridColDef<Machine>[] = [
  { field: 'hostname', headerName: 'Hostname', flex: 1, minWidth: 160 },
  { field: 'os', headerName: 'OS', flex: 1.2, minWidth: 180 },
  {
    field: 'online', headerName: 'Status', width: 110,
    renderCell: (p) => <OnlineChip online={p.row.online} />,
  },
  {
    field: 'last_seen', headerName: 'Last seen', width: 170,
    valueFormatter: (v: string | null) => timeAgo(v),
    renderCell: (p) => <span title={fmtDate(p.row.last_seen)}>{timeAgo(p.row.last_seen)}</span>,
  },
  { field: 'software_count', headerName: 'Apps', type: 'number', width: 90 },
  { field: 'port_count', headerName: 'Ports', type: 'number', width: 90 },
  { field: 'process_count', headerName: 'Processes', type: 'number', width: 110 },
  { field: 'service_count', headerName: 'Services', type: 'number', width: 100 },
  { field: 'snapshot_count', headerName: 'Snapshots', type: 'number', width: 110 },
]

export default function Machines() {
  const { data, isLoading, error } = useMachines()
  const navigate = useNavigate()
  if (error) return <ErrorBox error={error} />
  return (
    <>
      <PageHeader title="Machines" subtitle="Counts are from each machine's latest snapshot. Click a row for details." />
      <Paper sx={{ height: 'calc(100vh - 220px)', minHeight: 400 }}>
        <DataGrid
          rows={data?.items ?? []}
          columns={columns}
          loading={isLoading}
          showToolbar
          density="compact"
          disableRowSelectionOnClick
          onRowClick={(p) => navigate(`/machines/${p.id}`)}
          initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
          pageSizeOptions={[25, 50, 100]}
          sx={{ border: 0, '& .MuiDataGrid-row': { cursor: 'pointer' } }}
        />
      </Paper>
    </>
  )
}
