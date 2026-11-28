import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    watch: {
      // Test artefacts are rewritten while the dev server is running; watching
      // them makes the file watcher throw EBUSY on Windows and kills the server.
      ignored: [
        '**/playwright-report/**',
        '**/test-results/**',
        '**/coverage/**',
        '**/dist/**',
      ],
    },
    proxy: {
      // In development the API is proxied so tracking links and cookies work
      // against a single origin.
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      // /training/{tracking_uuid} is an SPA route and must stay with Vite. It used
      // to be proxied to the backend, which answered with the *built* index.html:
      // that document points at /assets/*.js, and the dev server does not serve
      // those hashed files, so the training page rendered as a blank screen and
      // recorded nothing. Only the API is proxied now.
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
});
