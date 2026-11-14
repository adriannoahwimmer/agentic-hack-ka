/**
 * Einstieg des Frontends: baut den Kern (ctx), lädt alle Feature-Module, startet das Spiel.
 *
 * Registrierungspunkt (Vertrag, Design.md): Jede Datei in ./features/*.js
 * exportiert `init(ctx)` und registriert dort ihre Handler (ctx.net.on, ctx.onUpdate, ...).
 * Feature-Scheiben ändern diese Datei nicht. Ein Fehler in einem Feature
 * stoppt die anderen nicht.
 */
import { createCore } from './core/index.js';
import { createNet } from './net.js';

const features = import.meta.glob('./features/*.js', { eager: true });

/** Kern bauen, Features initialisieren, Verbindung und Spielschleife starten. */
async function boot() {
  const net = createNet();
  const ctx = await createCore({ net });
  for (const [path, mod] of Object.entries(features)) {
    if (typeof mod.init !== 'function') {
      console.warn(`[features] ${path} exportiert kein init(ctx)`);
      continue;
    }
    try {
      mod.init(ctx);
      console.info(`[features] ${path} geladen`);
    } catch (err) {
      console.error(`[features] ${path}: init fehlgeschlagen`, err);
    }
  }
  net.connect();
  ctx.start();
}

boot();
