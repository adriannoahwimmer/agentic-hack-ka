/**
 * Prozedurale Fassaden: Fenster und Geschosse per Shader aus Weltkoordinaten (Look-Pass).
 *
 * Zweck: Die extrudierten OSM-Gebäude haben keine UVs. Ein onBeforeCompile-Patch des
 * MeshStandardMaterial zeichnet Fensterraster (Geschosshöhe 3,2 m wie im Bake, Achsmaß 3 m)
 * auf alle Wände; Scheiben sind dunkel und glatt und spiegeln dadurch das HDRI.
 * Use-Cases: Gebäude-Mesh `city-buildings` beim Material-Upgrade (look/index.js).
 */
import * as THREE from 'three';

const FLOOR_M = '3.2';
const BAY_M = '3.0';

/**
 * Standard-Material mit Fensterraster.
 * @param {THREE.MeshLambertMaterial|THREE.MeshStandardMaterial} base Ausgangsmaterial (Vertex-Farben)
 */
export function facadeMaterial(base) {
  const m = new THREE.MeshStandardMaterial({
    vertexColors: true, side: base.side, roughness: 0.9, metalness: 0.0,
  });
  m.name = 'facade';
  m.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vFacadePos;\nvarying vec3 vFacadeNrm;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vFacadePos = (modelMatrix * vec4(transformed, 1.0)).xyz;
        vFacadeNrm = normalize(mat3(modelMatrix) * objectNormal);`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vFacadePos;\nvarying vec3 vFacadeNrm;\nfloat facadeWin = 0.0;')
      .replace('#include <color_fragment>', `#include <color_fragment>
        {
          float wall = 1.0 - smoothstep(0.3, 0.6, abs(vFacadeNrm.y));
          float along = abs(vFacadeNrm.x) > abs(vFacadeNrm.z) ? vFacadePos.z : vFacadePos.x;
          float fx = fract(along / ${BAY_M});
          float fy = fract(vFacadePos.y / ${FLOOR_M});
          bool ground = vFacadePos.y < ${FLOOR_M};
          float x0 = ground ? 0.12 : 0.28; float x1 = ground ? 0.88 : 0.72;
          float y0 = ground ? 0.12 : 0.32; float y1 = ground ? 0.78 : 0.80;
          float win = step(x0, fx) * step(fx, x1) * step(y0, fy) * step(fy, y1);
          // Gesims zwischen den Geschossen: leicht dunkler.
          float ledge = (1.0 - step(0.06, fy)) * wall * 0.12;
          facadeWin = win * wall;
          diffuseColor.rgb *= 1.0 - ledge;
          diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.045, 0.06, 0.08), facadeWin);
        }`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
        roughnessFactor = mix(roughnessFactor, 0.08, facadeWin);`);
  };
  return m;
}
