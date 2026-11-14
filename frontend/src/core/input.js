/**
 * Tastatur und Maus mit Pointer-Lock (Scheibe Welt).
 *
 * Zweck: ctx.input (`isDown(code)`, `onKey(code, fn)`) plus Mausbewegung und
 * Maustasten für Kamera und Ballern.
 * Use-Cases: WASD-Steuerung, E zum Reden (Quest-NPC), F zum Einsteigen, L fürs Overlay.
 * Codes sind KeyboardEvent.code (z. B. 'KeyW', 'ShiftLeft', 'Digit1').
 * Tasten in Eingabefeldern (z. B. Dialog-Textfeld) werden ignoriert.
 */

/**
 * Input-Zustand an ein Canvas binden. Klick aufs Canvas fordert Pointer-Lock an.
 * @param {HTMLElement} canvas
 */
export function createInput(canvas) {
  const down = new Set();
  const keyHandlers = new Map();
  const mouse = { dx: 0, dy: 0, buttons: new Set(), clickHandlers: new Set() };

  /** True, wenn das Ereignis aus einem Eingabefeld kommt. */
  const fromField = (e) => e.target instanceof HTMLElement && e.target.matches('input, textarea, select, [contenteditable]');

  addEventListener('keydown', (e) => {
    if (fromField(e)) return;
    if (e.code === 'Tab' || e.code === 'Space') e.preventDefault();
    if (!e.repeat) {
      for (const fn of keyHandlers.get(e.code) ?? []) {
        try { fn(); } catch (err) { console.error(`[input] ${e.code}`, err); }
      }
    }
    down.add(e.code);
  });
  addEventListener('keyup', (e) => down.delete(e.code));
  addEventListener('blur', () => { down.clear(); mouse.buttons.clear(); });

  canvas.addEventListener('click', () => {
    if (document.pointerLockElement !== canvas) {
      // Kann abgelehnt werden (z. B. direkt nach Esc); dann einfach erneut klicken.
      Promise.resolve(canvas.requestPointerLock?.()).catch(() => {});
    }
  });
  addEventListener('mousemove', (e) => {
    if (document.pointerLockElement !== canvas) return;
    mouse.dx += e.movementX;
    mouse.dy += e.movementY;
  });
  addEventListener('mousedown', (e) => {
    if (document.pointerLockElement !== canvas) return;
    mouse.buttons.add(e.button);
    for (const fn of mouse.clickHandlers) fn(e.button);
  });
  addEventListener('mouseup', (e) => mouse.buttons.delete(e.button));

  return {
    /** @param {string} code KeyboardEvent.code */
    isDown: (code) => down.has(code),
    /**
     * Handler für Tastendruck (ohne Auto-Repeat). Gibt eine Abmeldefunktion zurück.
     * @param {string} code
     * @param {() => void} fn
     */
    onKey(code, fn) {
      if (!keyHandlers.has(code)) keyHandlers.set(code, new Set());
      keyHandlers.get(code).add(fn);
      return () => keyHandlers.get(code)?.delete(fn);
    },
    /** Mausbewegung seit dem letzten Aufruf (Pixel) abholen und zurücksetzen. */
    takeMouseDelta() {
      const d = { dx: mouse.dx, dy: mouse.dy };
      mouse.dx = 0;
      mouse.dy = 0;
      return d;
    },
    /** @param {number} button 0 = links */
    isMouseDown: (button) => mouse.buttons.has(button),
    /** Handler für Mausklick im Pointer-Lock. */
    onMouseDown(fn) {
      mouse.clickHandlers.add(fn);
      return () => mouse.clickHandlers.delete(fn);
    },
    /** True, wenn das Spiel die Maus hat (Pointer-Lock aktiv). */
    locked: () => document.pointerLockElement === canvas,
  };
}
