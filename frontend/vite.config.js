/**
 * Vite-Konfiguration für Fächerstadt Agents.
 *
 * Zweck: Dev-Server mit Proxy zum FastAPI-Backend und Build nach ../static,
 * das FastAPI unter /play/ ausliefert.
 * Use-Cases: `npm run dev` pro Worktree, `npm run build` für check.ps1 und die Abgabe.
 * Ports: PORT bzw. BACKEND_PORT (Backend) und VITE_PORT aus der .env im Projektordner
 * (scripts/setup-worktree.ps1 setzt sie) oder aus frontend/.env.local (hat Vorrang).
 * Aus der Projekt-.env werden nur diese Port-Schlüssel gelesen, nie der API-Key.
 */
import { fileURLToPath } from 'node:url';
import { defineConfig, loadEnv } from 'vite';

const here = fileURLToPath(new URL('.', import.meta.url));
const projectRoot = fileURLToPath(new URL('..', import.meta.url));
const PORT_KEYS = ['PORT', 'BACKEND_PORT', 'VITE_PORT'];

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, projectRoot, PORT_KEYS), ...loadEnv(mode, here, PORT_KEYS) };
  const backendPort = Number(env.BACKEND_PORT || env.PORT || 3000);
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
