/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/_/app/',
  plugins: [react()],
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
      '/_/assets': {
        target: 'http://127.0.0.1:9099',
        changeOrigin: true,
      },
      '/_/review': {
        target: 'http://127.0.0.1:9099',
        changeOrigin: true,
      },
    },
  },
});
