import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import spec from '../house.json';
import config from '../../config/cameras.json';
import { createMaterials, createIdMaterials, MATERIALS } from './materials.js';
import { buildHouse } from './house.js';
import { renderPasses } from './passes.js';

// Two modes:
//   /?export=1       headless: exposes window.renderPasses(camId) for scripts/export-passes.mjs
//   /?cam=street     interactive preview from a camera; drag to orbit, press "p" to log the pose
const params = new URLSearchParams(location.search);
const EXPORT = params.has('export');
const { width: W, height: H } = config;

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color('#c9d8e4');
const house = buildHouse(spec, createMaterials());
scene.add(house);

// Sun from azimuth/elevation: azimuth 0 = from the back (+z), 180 = from the street (-z).
const { sunAzimuthDeg, sunElevationDeg } = config.lighting;
const az = THREE.MathUtils.degToRad(sunAzimuthDeg);
const el = THREE.MathUtils.degToRad(sunElevationDeg);
const center = new THREE.Vector3(spec.lot.width / 2, 0, 16);
const sun = new THREE.DirectionalLight('#fff4e5', 3.2);
sun.position.copy(center).add(new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el)).multiplyScalar(80));
sun.target.position.copy(center);
sun.castShadow = true;
sun.shadow.mapSize.set(4096, 4096);
Object.assign(sun.shadow.camera, { left: -45, right: 45, top: 45, bottom: -45, near: 1, far: 200 });
sun.shadow.bias = -0.0003;
sun.shadow.normalBias = 0.03;
scene.add(sun, sun.target, new THREE.HemisphereLight('#d6e6f5', '#9a8f7c', 1.3));

const camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 500);
// `shift` = vertical lens shift as a fraction of the frame height (architectural
// photography: keep the camera level so verticals stay vertical, shift the frame up).
// `fov` is the vertical FOV of the full, unshifted frame.
function setCamera(cam) {
  const shift = cam.shift ?? 0;
  const fullH = H * (1 + 2 * shift);
  camera.fov = cam.fov;
  camera.aspect = W / fullH;
  if (shift) camera.setViewOffset(W, fullH, 0, 0, W, H);
  else camera.clearViewOffset();
  camera.position.fromArray(cam.pos);
  camera.lookAt(new THREE.Vector3().fromArray(cam.target));
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
}
const camById = (id) => config.cameras.find((c) => c.id === id) ?? config.cameras[0];

const idMaterials = createIdMaterials();
const idTable = Object.fromEntries(Object.entries(MATERIALS).map(([k, m]) => [m.id.join(','), k]));

if (EXPORT) {
  // GLB for ComfyUI's Load3D node: the same procedural house, as a file the graph can load
  window.exportGLB = async () => {
    const { GLTFExporter } = await import('three/addons/exporters/GLTFExporter.js');
    const buf = await new GLTFExporter().parseAsync(house, { binary: true, onlyVisible: true });
    let s = '';
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };
  window.renderPasses = (camId) => {
    const cam = camById(camId);
    setCamera(cam);
    return renderPasses({ renderer, scene, camera, W, H, S: 2, idMaterials, idTable, depthRange: cam.depthRange });
  };
  const gl = renderer.getContext();
  const dbg = gl.getExtension('WEBGL_debug_renderer_info');
  window.__glRenderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  window.__ready = true;
} else {
  const cam = camById(params.get('cam'));
  setCamera(cam);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.fromArray(cam.target);
  controls.update();
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'p') return;
    const r = (v) => v.toArray().map((n) => +n.toFixed(2));
    console.log(JSON.stringify({ pos: r(camera.position), target: r(controls.target), fov: camera.fov }));
  });
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
}
