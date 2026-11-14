/**
 * Rapier-Physik mit festem Zeitschritt 1/60 s (Scheibe Welt).
 *
 * Zweck: ctx.rapier (initialisiertes Modul) und ctx.physics (RAPIER.World).
 * Use-Cases: Character-Controller des Spielers, Fahrzeuge, statischer Stadt-Collider;
 * Feature-Scheiben legen eigene Bodies an (z. B. Polizeiautos).
 * `fixed(fn)` registriert Callbacks, die vor jedem Physikschritt laufen (für
 * Kinematik und Fahrzeugkräfte), damit sie mit genau 1/60 s rechnen.
 */
import RAPIER from '@dimforge/rapier3d-compat';

/** Fester Physik-Zeitschritt in s. */
export const FIXED_DT = 1 / 60;
const MAX_SUBSTEPS = 5;

/**
 * Rapier initialisieren und eine Welt mit Schwerkraft anlegen.
 * @returns {Promise<{RAPIER: typeof RAPIER, world: object, step: (dt: number) => void, fixed: (fn: (dt: number) => void) => () => void}>}
 */
export async function createPhysics() {
  await RAPIER.init();
  const world = new RAPIER.World({ x: 0, y: -9.81, z: 0 });
  world.timestep = FIXED_DT;
  const fixedFns = new Set();
  let acc = 0;

  /**
   * Physik um dt (Echtzeit) weiterschalten: so viele feste Schritte wie nötig, höchstens 5.
   * @param {number} dt
   */
  function step(dt) {
    acc = Math.min(acc + dt, FIXED_DT * MAX_SUBSTEPS);
    while (acc >= FIXED_DT) {
      for (const fn of fixedFns) fn(FIXED_DT);
      world.step();
      acc -= FIXED_DT;
    }
  }

  /**
   * Callback vor jedem festen Physikschritt registrieren. Gibt eine Abmeldefunktion zurück.
   * @param {(dt: number) => void} fn
   */
  function fixed(fn) {
    fixedFns.add(fn);
    return () => fixedFns.delete(fn);
  }

  return { RAPIER, world, step, fixed };
}
