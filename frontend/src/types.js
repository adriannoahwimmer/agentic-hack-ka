/**
 * Typen des Frontend-Vertrags (nur JSDoc, kein Laufzeitcode).
 *
 * Zweck: beschreibt `ctx`, das core/ (Scheibe Welt) baut und jedes Feature-Modul
 * in `init(ctx)` bekommt. Änderungen nur additiv, angekündigt in Design.md,
 * Abschnitt "Frontend-Kern". Koordinaten: Meter, x = Ost, z = Süd, y = oben.
 */

/**
 * @typedef {object} Net
 * @property {() => void} connect
 * @property {(type: string, payload: object) => boolean} send
 * @property {(type: string, payload: object, minIntervalMs: number) => void} sendThrottled
 * @property {(type: string, fn: (payload: object, envelope: object) => void) => () => void} on
 * @property {(fn: (connected: boolean) => void) => () => void} onStatus
 * @property {boolean} connected
 */

/**
 * @typedef {object} Vec2
 * @property {number} x Ost in Metern
 * @property {number} z Süd in Metern
 */

/**
 * @typedef {object} CombatTarget
 * @property {string} id eindeutig, wird zu npc_killed.npc_id
 * @property {'civilian'|'police'|'gang'|'quest_target'} kind wird zu npc_killed.npc_kind
 * @property {string} [questId] wird zu npc_killed.quest_id
 * @property {number} hp Treffer bis zum Tod
 * @property {() => void} [onKilled] Aufruf nach npc_killed; das Feature entfernt sein Objekt
 */

/**
 * @typedef {object} Ctx
 * @property {typeof import('three')} three
 * @property {import('three').Scene} scene
 * @property {import('three').PerspectiveCamera} camera
 * @property {import('three').WebGLRenderer} renderer
 * @property {object} rapier RAPIER-Modul (@dimforge/rapier3d-compat, initialisiert)
 * @property {object} physics RAPIER.World
 * @property {Net} net
 * @property {(fn: (dt: number, t: number) => void) => () => void} onUpdate pro Frame
 * @property {{isDown: (code: string) => boolean, onKey: (code: string, fn: () => void) => () => void}} input
 * @property {{position: () => Vec2, heading: () => number, inVehicle: () => boolean, object3d: import('three').Object3D}} player
 * @property {{pois: object[], zoneAt: (x: number, z: number) => (string|null), randomRoadPoint: (near: Vec2, minDist: number, maxDist: number) => Vec2}} world
 * @property {{addTarget: (object3d: import('three').Object3D, target: CombatTarget) => void, removeTarget: (id: string) => void}} combat
 * @property {{car: (opts?: {police?: boolean, color?: number}) => import('three').Object3D, person: (opts?: {color?: number}) => import('three').Object3D, setLightbar: (carObj: import('three').Object3D, phase: boolean) => void}} models
 * @property {{setWanted: (level: number) => void, toast: (text: string, ms?: number) => void, setObjective: (text: string|null) => void, subtitle: (text: string, ms?: number) => void, showDialog: (d: {speaker: string, text: string, sources?: {title: string, uri: string}[], pending?: boolean}) => void, hideDialog: () => void, addPanel: (id: string) => HTMLElement}} hud
 * @property {() => void} start Spielschleife starten (ruft main.js)
 */

export {};
