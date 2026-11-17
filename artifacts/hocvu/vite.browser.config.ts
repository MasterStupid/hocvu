import path from 'node:path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

// Frontend only. Never import run.py, proxy an API, or start FastAPI here.
export default defineConfig({
  root: import.meta.dirname,
  base: '/',
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'deny-browser-test-api',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (/^\/api(?:\/|\?|$)/.test(req.url || '')) {
            res.statusCode = 503;
            res.end('Browser test API was not intercepted');
          } else next();
        });
      },
    },
  ],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
    dedupe: ['react', 'react-dom'],
  },
  server: { host: '127.0.0.1', port: 4179, strictPort: true, hmr: false },
});
