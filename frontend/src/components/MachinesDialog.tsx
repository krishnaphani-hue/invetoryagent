import { Link as RouterLink } from 'react-router'
import { Dialog, DialogContent, DialogTitle, Link, List, ListItem, ListItemText } from '@mui/material'
import type { MachineRef } from '../api'

/** Lists the machines behind a grouped software / port row. */
export default function MachinesDialog({ title, machines, onClose }: { title: string; machines: MachineRef[] | null; onClose: () => void }) {
  return (
    <Dialog open={machines !== null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers>
        <List dense>
          {(machines ?? []).map((m, i) => (
            <ListItem key={`${m.id}-${i}`} disableGutters>
              <ListItemText
                primary={<Link component={RouterLink} to={`/machines/${m.id}`} onClick={onClose}>{m.hostname ?? m.id}</Link>}
                secondary={[m.local_address && `address ${m.local_address}`, m.version && `version ${m.version}`].filter(Boolean).join(' · ') || undefined}
              />
            </ListItem>
          ))}
        </List>
      </DialogContent>
    </Dialog>
  )
}
