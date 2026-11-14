/**
 * Vite-Konfiguration für Fächerstadt Agents.
 *
 * Zweck: Dev-Server mit Proxy zum FastAPI-Backend und Build nach ../static,
 * das FastAPI unter /play/ ausliefert.
 * Use-Cases: `npm run dev` pro Worktree (Ports aus frontend/.env.local:
 * BACKEND_PORT, VITE_PORT), `npm run build` für check.ps1 und die Abgabe.
 */
import { fileURLToPath } from 'node:url';
import { defineConfig, loadEnv } from 'vite';

const here = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, here, '');
  const backendPort = Number(env.BACKEND_PORT || 3000);
  const http = `http://localhost:${backendPort}`;

  return {
    root: here,
    base: '/play/',
    server: {
      port: Number(env.VITE_PORT || 5173),
      strictPort: true,
      // data/pois.json und data/npcs.json liegen eine Ebene höher (Python teilt sie).
      fs: { allow: ['..'] },
      proxy: {
        '/ws': { target: `ws://localhost:${backendPort}`, ws: true },
        '/npc': http,
        '/tts': http,
        '/debug': http,
      },
    },
    build: {
      outDir: '../static',
      emptyOutDir: true,
      chunkSizeWarningLimit: 2500, // three + rapier (WASM inline) sind groß
    },
  };
});
