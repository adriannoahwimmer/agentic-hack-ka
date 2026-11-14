/**
 * Feature-Einhängepunkt Spieler-Funk (main.js lädt features/*.js per Glob).
 *
 * Zweck: bindet ui/radioButtons.js ein (HUD-Buttons + Tasten G/T, sendet player_radio).
 * Use-Cases: Spieler bettelt (G) oder provoziert (T), der Polizei-Dispatcher antwortet per Funk.
 */
export { init } from '../ui/radioButtons.js';
