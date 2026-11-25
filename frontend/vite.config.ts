import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server on :5173 forwards /api to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 2000 }, // internal dashboard; one bundle is fine
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8000' },
  },
})
