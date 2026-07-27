/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/spa/',
  plugins: [react()],
  build: {
    outDir: '../backend/spa',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
  server: {
    proxy: {
      '/_/api': {
        target: 'http://127.0.0.1:9099',
        changeOrigin: true,
      },
      '/_/health': {
        target: 'http://127.0.0.1:9099',
        changeOrigin: true,
      },
      '^/(?!_|spa/|src/|@|node_modules/|fonts/|favicon\\.ico$).+/.+': {
        target: 'http://127.0.0.1:9099',
        changeOrigin: true,
      },
    },
  },
});
