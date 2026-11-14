/**
 * Dauerhafter OSM-Lizenzhinweis (Scheibe Welt).
 *
 * Zweck: Die ODbL verlangt einen sichtbaren Hinweis auf OpenStreetMap, solange die
 * Karte zu sehen ist. Use-Case: unten rechts "© OpenStreetMap contributors" mit Link
 * auf openstreetmap.org/copyright, klickbar, nie ausgeblendet.
 */

/**
 * Hinweis an den HUD-Container hängen.
 * @param {HTMLElement} root
 */
export function addAttribution(root) {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:8px;bottom:6px;font:12px system-ui,sans-serif;'
    + 'background:#ffffffcc;color:#222;padding:2px 6px;border-radius:3px;pointer-events:auto;text-shadow:none;z-index:10';
  const link = document.createElement('a');
  link.href = 'https://www.openstreetmap.org/copyright';
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.style.color = '#1a5fb4';
  link.textContent = '© OpenStreetMap contributors';
  box.appendChild(link);
  root.appendChild(box);
  return box;
}
