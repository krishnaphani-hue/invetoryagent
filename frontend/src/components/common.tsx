import type { ReactNode } from 'react'
import { Alert, Box, Card, CardContent, Chip, CircularProgress, Stack, Typography } from '@mui/material'
import { sourceLabel } from '../format'

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 3, justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
      <Box>
        <Typography variant="h5" sx={{ fontWeight: 600 }}>{title}</Typography>
        {subtitle && <Typography variant="body2" color="text.secondary">{subtitle}</Typography>}
      </Box>
      {action}
    </Stack>
  )
}

export function StatCard({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <Card>
      <CardContent>
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <Typography variant="body2" color="text.secondary">{label}</Typography>
          <Box sx={{ color: 'primary.main', display: 'flex' }}>{icon}</Box>
        </Stack>
        <Typography variant="h4" sx={{ fontWeight: 600, mt: 0.5 }}>{value}</Typography>
        {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
      </CardContent>
    </Card>
  )
}

export function Loading() {
  return <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}><CircularProgress /></Box>
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error)
  return <Alert severity="error">Could not load data: {msg}. Is the backend running?</Alert>
}

export function OnlineChip({ online }: { online: boolean }) {
  return <Chip size="small" label={online ? 'Online' : 'Offline'} color={online ? 'success' : 'default'} variant={online ? 'filled' : 'outlined'} />
}

export function SourceChip({ source }: { source: string }) {
  return <Chip size="small" variant="outlined" color={source === 'agent' ? 'primary' : 'secondary'} label={sourceLabel(source)} />
}

export function ExposedChip({ exposed }: { exposed: boolean }) {
  return exposed
    ? <Chip size="small" color="warning" label="Exposed" />
    : <Chip size="small" variant="outlined" label="Local only" />
}

/** Responsive card grid without the Grid component (stable across MUI versions). */
export function CardGrid({ min = 220, children }: { min?: number; children: ReactNode }) {
  return <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))` }}>{children}</Box>
}
