import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The backend's CORS allow-list is exactly http://localhost:5173. Without
    // strictPort Vite silently moves to 5174 when 5173 is taken, and every
    // dashboard request then fails with "Failed to fetch". Fail loudly instead.
    port: 5173,
    strictPort: true,
    // The dashboard calls /v1/... on its own origin and Vite forwards it to
    // the FastAPI server, so the browser never makes a cross-origin request.
    proxy: { '/v1': 'http://127.0.0.1:8001' },
  },
})
