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
      // The backend owns /training/{tracking_uuid} (the standalone micro-learning
      // page). The trailing slash matters: without it this prefix also captures
      // the SPA route /training-library.
      '/training/': {
        target: process.env.VITE_API_PROXY ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
});
