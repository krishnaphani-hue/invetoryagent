import { StrictMode, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material'
import App from './App'

// Every page re-fetches its data every 5 minutes so the dashboard shows recent deliveries without a reload.
const REFRESH_MS = 5 * 60_000

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, refetchInterval: REFRESH_MS } },
})

function readMode(): 'light' | 'dark' {
  try {
    const saved = localStorage.getItem('theme-mode')
    if (saved === 'light' || saved === 'dark') return saved
  } catch { /* storage unavailable */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function Root() {
  const [mode, setMode] = useState<'light' | 'dark'>(readMode)
  const theme = useMemo(
    () => createTheme({
      palette: { mode, primary: { main: '#1565c0' }, background: mode === 'light' ? { default: '#f4f6f9' } : {} },
      shape: { borderRadius: 10 },
      components: { MuiCard: { defaultProps: { variant: 'outlined' } }, MuiPaper: { defaultProps: { variant: 'outlined' } } },
    }),
    [mode],
  )
  const toggle = () => {
    const next = mode === 'light' ? 'dark' : 'light'
    setMode(next)
    try { localStorage.setItem('theme-mode', next) } catch { /* ignore */ }
  }
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App mode={mode} onToggleMode={toggle} />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
