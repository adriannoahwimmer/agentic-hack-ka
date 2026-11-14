/**
 * Polizeisirene per Web Audio API (Scheibe Polizei, Polish).
 *
 * Zweck: Heulton (Wail) ohne Audio-Asset: Sägezahn-Oszillator, dessen Frequenz ein
 * langsamer Sinus-LFO zwischen ca. 600 und 1300 Hz auf- und abfahren lässt, durch einen
 * Tiefpass. Die Lautstärke hängt von der Distanz zum nächsten Streifenwagen ab.
 * Use-Cases:
 * - police.js ruft pro Frame `update(level, nearestDistance)` auf
 * - Level 0 oder keine Einheit → stumm (sanft ausgeblendet)
 * - je höher das Level, desto schneller heult die Sirene
 * Der AudioContext entsteht erst nach einer Nutzergeste (Autoplay-Regeln der Browser).
 */

const BASE_HZ = 950;
const SWEEP_HZ = 350;
const MAX_GAIN = 0.08;
const NEAR_M = 15;
const FAR_M = 260;
const SMOOTH_S = 0.15;

/**
 * Lautstärke 0..1 nach Distanz: voll bis NEAR_M, quadratisch abfallend bis FAR_M.
 * @param {number} d Distanz in m
 */
function falloff(d) {
  const t = Math.min(1, Math.max(0, (FAR_M - d) / (FAR_M - NEAR_M)));
  return t * t;
}

/**
 * Sirene anlegen. Ohne Web Audio (alter Browser) bleibt `update` wirkungslos.
 * @returns {{update: (level: number, nearestDistance: number) => void}}
 */
export function createSiren() {
  /** @type {{ac: AudioContext, gain: GainNode, lfo: OscillatorNode} | null} */
  let graph = null;

  /** Audio-Graph beim ersten Klick oder Tastendruck bauen. */
  const unlock = () => {
    window.removeEventListener('pointerdown', unlock);
    window.removeEventListener('keydown', unlock);
    try {
      const ac = new AudioContext();
      const osc = ac.createOscillator();
      osc.type = 'sawtooth';
      osc.frequency.value = BASE_HZ;
      const lfo = ac.createOscillator();
      lfo.type = 'sine';
      lfo.frequency.value = 0.25;
      const depth = ac.createGain();
      depth.gain.value = SWEEP_HZ;
      lfo.connect(depth).connect(osc.frequency);
      const tone = ac.createBiquadFilter();
      tone.type = 'lowpass';
      tone.frequency.value = 2200;
      const gain = ac.createGain();
      gain.gain.value = 0;
      osc.connect(tone).connect(gain).connect(ac.destination);
      osc.start();
      lfo.start();
      graph = { ac, gain, lfo };
    } catch (err) {
      console.warn('[siren] Web Audio nicht verfügbar', err);
    }
  };
  window.addEventListener('pointerdown', unlock);
  window.addEventListener('keydown', unlock);

  return {
    /**
     * Lautstärke und Heul-Tempo nachführen (pro Frame).
     * @param {number} level Fahndungsstufe 0-5
     * @param {number} nearestDistance Distanz zum nächsten Streifenwagen in m (Infinity = keiner)
     */
    update(level, nearestDistance) {
      if (!graph) return;
      const now = graph.ac.currentTime;
      const target = level > 0 ? MAX_GAIN * falloff(nearestDistance) : 0;
      graph.gain.gain.setTargetAtTime(target, now, SMOOTH_S);
      graph.lfo.frequency.setTargetAtTime(0.18 + 0.06 * Math.max(1, level), now, 0.5);
    },
  };
}
