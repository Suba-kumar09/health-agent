import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The backend's CORS allow-list is exactly http://localhost:5173. Without
  // strictPort Vite silently moves to 5174 when 5173 is taken, and every
  // dashboard request then fails with "Failed to fetch". Fail loudly instead.
  server: { port: 5173, strictPort: true },
})
