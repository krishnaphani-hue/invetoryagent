import { useState, type ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router'
import {
  AppBar, Box, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Toolbar, Tooltip, Typography,
  useMediaQuery, useTheme,
} from '@mui/material'
import DashboardIcon from '@mui/icons-material/DashboardOutlined'
import ComputerIcon from '@mui/icons-material/ComputerOutlined'
import AppsIcon from '@mui/icons-material/AppsOutlined'
import LanIcon from '@mui/icons-material/LanOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import UploadIcon from '@mui/icons-material/UploadFileOutlined'
import DarkIcon from '@mui/icons-material/DarkModeOutlined'
import LightIcon from '@mui/icons-material/LightModeOutlined'
import MenuIcon from '@mui/icons-material/Menu'
import Dashboard from './pages/Dashboard'
import Machines from './pages/Machines'
import MachineDetail from './pages/MachineDetail'
import Software from './pages/Software'
import Ports from './pages/Ports'
import Snapshots from './pages/Snapshots'
import Upload from './pages/Upload'

const DRAWER_WIDTH = 220

const NAV: { to: string; label: string; icon: ReactNode }[] = [
  { to: '/', label: 'Dashboard', icon: <DashboardIcon /> },
  { to: '/machines', label: 'Machines', icon: <ComputerIcon /> },
  { to: '/software', label: 'Software', icon: <AppsIcon /> },
  { to: '/ports', label: 'Ports', icon: <LanIcon /> },
  { to: '/snapshots', label: 'Snapshots', icon: <HistoryIcon /> },
  { to: '/upload', label: 'Upload Excel', icon: <UploadIcon /> },
]

export default function App({ mode, onToggleMode }: { mode: 'light' | 'dark'; onToggleMode: () => void }) {
  const theme = useTheme()
  const desktop = useMediaQuery(theme.breakpoints.up('md'))
  const [open, setOpen] = useState(false)

  const nav = (
    <List sx={{ px: 1 }}>
      {NAV.map((item) => (
        <ListItemButton
          key={item.to}
          component={NavLink}
          to={item.to}
          end={item.to === '/'}
          onClick={() => setOpen(false)}
          sx={{ borderRadius: 2, mb: 0.5, '&.active': { bgcolor: 'action.selected', color: 'primary.main' },
                '&.active .MuiListItemIcon-root': { color: 'primary.main' } }}
        >
          <ListItemIcon sx={{ minWidth: 38 }}>{item.icon}</ListItemIcon>
          <ListItemText primary={item.label} />
        </ListItemButton>
      ))}
    </List>
  )

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar position="fixed" color="inherit" elevation={0}
              sx={{ zIndex: (t) => t.zIndex.drawer + 1, borderBottom: 1, borderColor: 'divider' }}>
        <Toolbar>
          {!desktop && (
            <IconButton edge="start" onClick={() => setOpen(true)} sx={{ mr: 1 }} aria-label="menu"><MenuIcon /></IconButton>
          )}
          <ComputerIcon color="primary" sx={{ mr: 1 }} />
          <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 600 }}>Asset Inventory</Typography>
          <Tooltip title={mode === 'light' ? 'Dark mode' : 'Light mode'}>
            <IconButton onClick={onToggleMode}>{mode === 'light' ? <DarkIcon /> : <LightIcon />}</IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      <Drawer
        variant={desktop ? 'permanent' : 'temporary'}
        open={desktop || open}
        onClose={() => setOpen(false)}
        sx={{ width: DRAWER_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' } }}
      >
        <Toolbar />
        {nav}
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: { xs: 2, md: 3 } }}>
        <Toolbar />
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/machines" element={<Machines />} />
          <Route path="/machines/:id" element={<MachineDetail />} />
          <Route path="/software" element={<Software />} />
          <Route path="/ports" element={<Ports />} />
          <Route path="/snapshots" element={<Snapshots />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Box>
    </Box>
  )
}
