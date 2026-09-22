import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Allows the dev server to be reached through a Cloudflare Tunnel /
    // ngrok-style hostname during local demo/review, in addition to localhost.
    allowedHosts: [".trycloudflare.com"],
  },
})
