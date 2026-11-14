/**
 * Quest-Anzeige: Missionsziel, Zielmarker, Richtungspfeil und Quest-Gegner.
 *
 * Zweck: setzt quest_update vom Server (quests.py) im Spiel um. Ob ein Ziel erreicht
 * oder die Quest erfüllt ist, entscheidet nur der Server.
 * Use-Cases:
 * - active: Objective oben links, Lichtsäule am Ziel, Pfeil über dem Spieler
 * - target_reached: spawn_targets Gegner im POI-Radius (combat kind quest_target),
 *   sie laufen auf den Spieler zu und zeigen Mündungsfeuer ohne Schaden
 * - completed: Toast "Mission complete", Marker und Gegner weg
 */

const ENEMY_SPEED = 2.2; // m/s
const ENEMY_STOP = 7; // m Abstand zum Spieler
const ENEMY_HP = 3;
const FLASH_EVERY = 1.4; // s (mit Zufall)

/**
 * Feature-Einstieg: Handler für quest_update und Update-Schleife.
 * @param {import('../types.js').Ctx} ctx
 */
export function init(ctx) {
  const THREE = ctx.three;
  let quest = null;
  const spawnedFor = new Set();
  /** @type {{id: string, obj: object, flash: object, cooldown: number}[]} */
  let enemies = [];

  // Lichtsäule am Ziel
  const beam = new THREE.Mesh(
    new THREE.CylinderGeometry(1, 1, 120, 16, 1, true),
    new THREE.MeshBasicMaterial({ color: 0xffd23f, transparent: true, opacity: 0.35, depthWrite: false, side: THREE.DoubleSide }),
  );
  beam.position.y = 60;
  beam.visible = false;
  ctx.scene.add(beam);

  // Richtungspfeil über dem Spieler
  const arrow = new THREE.Mesh(
    new THREE.ConeGeometry(0.35, 1.1, 8),
    new THREE.MeshBasicMaterial({ color: 0xffd23f }),
  );
  arrow.geometry.rotateX(Math.PI / 2); // Spitze zeigt nach +z
  arrow.visible = false;
  ctx.scene.add(arrow);

  /** Objective-Text aus dem Quest-Zustand. */
  function objectiveText(q) {
    if (q.status === 'target_reached') return `${q.title}: ${q.remaining} left`;
    return `${q.title}: ${q.objective}`;
  }

  /** Alle Quest-Gegner entfernen (ohne Event). */
  function clearEnemies() {
    for (const e of enemies) {
      ctx.combat.removeTarget(e.id);
      ctx.scene.remove(e.obj);
    }
    enemies = [];
  }

  /**
   * n Gegner im Radius des Ziels erzeugen.
   * @param {object} q quest_update-Payload
   * @param {number} n
   */
  function spawnEnemies(q, n) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const r = q.target.radius * (0.3 + 0.6 * Math.random());
      const obj = ctx.models.person({ color: 0xb3261e });
      obj.position.set(q.target.x + Math.cos(a) * r, 0, q.target.z + Math.sin(a) * r);
      const flash = new THREE.Mesh(
        new THREE.SphereGeometry(0.18, 6, 6),
        new THREE.MeshBasicMaterial({ color: 0xffe08a }),
      );
      flash.position.set(0.35, 1.35, 0.5);
      flash.visible = false;
      obj.add(flash);
      ctx.scene.add(obj);
      const id = `${q.quest_id}-t${i}-${Date.now() % 100000}`;
      const enemy = { id, obj, flash, cooldown: Math.random() * FLASH_EVERY };
      enemies.push(enemy);
      ctx.combat.addTarget(obj, {
        id, kind: 'quest_target', questId: q.quest_id, hp: ENEMY_HP,
        onKilled: () => {
          ctx.scene.remove(obj);
          enemies = enemies.filter((e) => e !== enemy);
        },
      });
    }
  }

  ctx.net.on('quest_update', (q) => {
    const isNew = !quest || quest.quest_id !== q.quest_id;
    if (isNew) clearEnemies();
    quest = q;
    if (q.status === 'completed') {
      ctx.hud.toast('Mission complete', 4000);
      ctx.hud.setObjective(null);
      beam.visible = false;
      arrow.visible = false;
      clearEnemies();
      quest = null;
      return;
    }
    if (isNew && q.status === 'active') ctx.hud.toast(`New mission: ${q.title}`, 3000);
    ctx.hud.setObjective(objectiveText(q));
    beam.position.set(q.target.x, 60, q.target.z);
    beam.scale.set(q.target.radius / 4, 1, q.target.radius / 4);
    beam.visible = q.status === 'active';
    arrow.visible = q.status === 'active';
    if (q.status === 'target_reached' && q.spawn_targets > 0 && !spawnedFor.has(q.quest_id)) {
      spawnedFor.add(q.quest_id);
      ctx.hud.toast('Here they come!', 2500);
      spawnEnemies(q, q.spawn_targets);
    }
  });

  ctx.onUpdate((dt) => {
    if (!quest) return;
    const p = ctx.player.position();
    if (arrow.visible) {
      arrow.position.set(p.x, 3.2, p.z);
      arrow.rotation.y = Math.atan2(quest.target.x - p.x, quest.target.z - p.z);
    }
    for (const e of enemies) {
      const dx = p.x - e.obj.position.x;
      const dz = p.z - e.obj.position.z;
      const d = Math.hypot(dx, dz);
      e.obj.rotation.y = Math.atan2(dx, dz);
      if (d > ENEMY_STOP) {
        e.obj.position.x += (dx / d) * ENEMY_SPEED * dt;
        e.obj.position.z += (dz / d) * ENEMY_SPEED * dt;
      }
      e.cooldown -= dt;
      if (e.cooldown <= 0 && d < 40) {
        e.flash.visible = true;
        e.cooldown = FLASH_EVERY * (0.6 + Math.random() * 0.8);
      } else if (e.cooldown < FLASH_EVERY * 0.5) {
        e.flash.visible = false;
      }
    }
  });
}
