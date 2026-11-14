/**
 * Feature-Einhängepunkt Agent-Overlay (main.js lädt features/*.js per Glob).
 *
 * Zweck: bindet ui/agentOverlay.js ein (Panel oben rechts mit den letzten agent_log-Einträgen).
 * Use-Cases: Agenten-Entscheidungen im Spiel und im Demo-Video sichtbar machen; Taste L toggelt.
 */
export { init } from '../ui/agentOverlay.js';
