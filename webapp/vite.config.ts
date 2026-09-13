import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// The console is served two ways, and must work under both without rebuilding
// asset URLs by hand:
//   • dev  — Vite dev server at http://localhost:5173/console/ (API is proxied)
//   • prod — FastAPI StaticFiles mounted at /console (same origin as /api/v1)
// A non-root, absolute base makes every emitted asset URL /console/… so it
// resolves under the mount, while /api/v1 stays absolute and hits the backend.
export default defineConfig({
  base: '/console/',
  assetsInclude: ['**/*.glb'],
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
})
