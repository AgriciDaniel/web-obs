import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { webObsDevApiPlugin } from './src/server/captureApi';

export default defineConfig({
  plugins: [react(), webObsDevApiPlugin()],
  base: './',
  build: {
    target: 'es2022',
    outDir: 'dist',
  },
});
