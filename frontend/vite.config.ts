import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs on :8000 (uvicorn backend.api:app); proxying keeps the browser on one origin.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
