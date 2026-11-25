import { useRef, useState, type DragEvent } from 'react'
import { Link as RouterLink } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import {
  Alert, Box, Button, Card, CardContent, LinearProgress, Link, Paper, Stack, Table, TableBody, TableCell, TableHead,
  TableRow, Typography,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUploadOutlined'
import { http, type UploadError, type UploadResult } from '../api'
import { PageHeader } from '../components/common'
import { countLabel } from '../format'

const SHEETS: [string, string][] = [
  ['machines', 'hostname, os, machine_id (optional sheet)'],
  ['installed_software', 'hostname, name, version, publisher'],
  ['listening_ports', 'hostname, protocol, local_address, port, pid, process_name, path, version'],
  ['processes', 'hostname, name, pid, path, version'],
  ['services', 'hostname, name, display_name, status, start_type'],
]

export default function Upload() {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<UploadResult | null>(null)
  const [errors, setErrors] = useState<UploadError[] | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const pick = (f: File | undefined) => {
    setResult(null); setErrors(null); setMessage(null)
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.xlsx')) { setMessage('Only .xlsx files are supported.'); setFile(null); return }
    setFile(f)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault(); setDragging(false)
    pick(e.dataTransfer.files?.[0])
  }

  const submit = async () => {
    if (!file) return
    setBusy(true); setResult(null); setErrors(null); setMessage(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const { data } = await http.post<UploadResult>('/uploads', form)
      setResult(data)
      queryClient.invalidateQueries()
    } catch (err) {
      if (axios.isAxiosError(err) && err.response) {
        const body = err.response.data as { detail?: unknown; errors?: UploadError[] }
        if (body.errors) setErrors(body.errors)
        setMessage(typeof body.detail === 'string' ? body.detail : `Upload failed (${err.response.status}).`)
      } else {
        setMessage('Upload failed: the server could not be reached.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title="Upload Excel" subtitle="For machines without the collector. Each machine in the file becomes a new snapshot." />

      <Paper
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
        sx={{ p: 5, textAlign: 'center', cursor: 'pointer', borderStyle: 'dashed', borderWidth: 2,
              borderColor: dragging ? 'primary.main' : 'divider', bgcolor: dragging ? 'action.hover' : 'background.paper' }}
      >
        <CloudUploadIcon color="primary" sx={{ fontSize: 48 }} />
        <Typography variant="h6">{file ? file.name : 'Drop an .xlsx file here, or click to choose'}</Typography>
        {file && <Typography variant="body2" color="text.secondary">{(file.size / 1024).toFixed(1)} KB</Typography>}
        <input ref={input} type="file" accept=".xlsx" hidden onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
      </Paper>

      <Stack direction="row" spacing={2} sx={{ mt: 2, alignItems: 'center' }}>
        <Button variant="contained" disabled={!file || busy} onClick={submit} startIcon={<CloudUploadIcon />}>Import</Button>
        {file && !busy && <Button onClick={() => pick(undefined)}>Clear</Button>}
      </Stack>
      {busy && <LinearProgress sx={{ mt: 2 }} />}

      {message && <Alert severity="error" sx={{ mt: 2 }}>{message} {errors ? 'Nothing was saved.' : ''}</Alert>}
      {errors && errors.length > 0 && (
        <Paper sx={{ mt: 1 }}>
          <Table size="small">
            <TableHead><TableRow><TableCell>Sheet</TableCell><TableCell>Row</TableCell><TableCell>Problem</TableCell></TableRow></TableHead>
            <TableBody>
              {errors.map((e, i) => (
                <TableRow key={i}><TableCell>{e.sheet ?? '—'}</TableCell><TableCell>{e.row ?? '—'}</TableCell><TableCell>{e.error}</TableCell></TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      {result && (
        <Card sx={{ mt: 2 }}>
          <CardContent>
            <Alert severity="success" sx={{ mb: 2 }}>
              Imported {result.filename}: {result.snapshots.length} machine{result.snapshots.length === 1 ? '' : 's'}, one new snapshot each.
            </Alert>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Machine</TableCell><TableCell align="right">Software</TableCell><TableCell align="right">Ports</TableCell>
                  <TableCell align="right">Processes</TableCell><TableCell align="right">Services</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {result.snapshots.map((s) => (
                  <TableRow key={s.snapshot_id}>
                    <TableCell><Link component={RouterLink} to={`/machines/${s.machine_id}`}>{s.hostname ?? s.machine_id}</Link></TableCell>
                    <TableCell align="right">{countLabel(s.counts.installed_software)}</TableCell>
                    <TableCell align="right">{countLabel(s.counts.listening_ports)}</TableCell>
                    <TableCell align="right">{countLabel(s.counts.processes)}</TableCell>
                    <TableCell align="right">{countLabel(s.counts.services)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card sx={{ mt: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>File format</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            One sheet per table, first row = column names. Every row needs a <b>hostname</b>. Sheets you leave out are not
            changed for that machine. Extra columns are kept. If any row is invalid, nothing is saved.
          </Typography>
          <Box component="ul" sx={{ m: 0, pl: 3 }}>
            {SHEETS.map(([sheet, cols]) => (
              <li key={sheet}><Typography variant="body2"><b>{sheet}</b>: {cols}</Typography></li>
            ))}
          </Box>
        </CardContent>
      </Card>
    </>
  )
}
