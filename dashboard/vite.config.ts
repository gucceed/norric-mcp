import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Vite proxies /mcp → localhost:8080 in dev so the dashboard can call the
// FastMCP backend with no CORS dance. Override the backend port via env
// var NORRIC_BACKEND if it lives elsewhere.
const BACKEND = process.env.NORRIC_BACKEND ?? 'http://localhost:8080';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/mcp': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
});
