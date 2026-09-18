import * as THREE from 'three';

// Render passes for ControlNet / QA. Beauty goes to the canvas; everything else is a
// G-buffer rendered at S x resolution into raw render targets, processed on the CPU
// and box-filtered down to the output size (cheap supersampling, no MSAA artifacts
// in the ID map).

const depthMaterial = new THREE.ShaderMaterial({
  vertexShader: /* glsl */ `
    varying float vViewZ;
    void main() {
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      vViewZ = -mv.z;
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: /* glsl */ `
    varying float vViewZ;
    void main() { gl_FragColor = vec4(vViewZ, 0.0, 0.0, 1.0); }`,
});
const normalMaterial = new THREE.MeshNormalMaterial();

const EDGE = {
  normalCos: Math.cos(THREE.MathUtils.degToRad(35)), // crease angle
  depthRel: 0.035, // relative view-depth jump
};

function readTarget(renderer, rt, ArrayType) {
  const buf = new ArrayType(rt.width * rt.height * 4);
  renderer.readRenderTargetPixels(rt, 0, 0, rt.width, rt.height, buf);
  return buf;
}

function renderTo(renderer, scene, camera, rt, { override = null, swap = null } = {}) {
  const bg = scene.background;
  scene.background = null;
  scene.overrideMaterial = override;
  const restore = [];
  if (swap) {
    scene.traverse((o) => {
      if (o.isMesh && o.userData.mat) { restore.push([o, o.material]); o.material = swap[o.userData.mat]; }
    });
  }
  renderer.setRenderTarget(rt);
  renderer.setClearColor(0x000000, 0);
  renderer.clear();
  renderer.render(scene, camera);
  renderer.setRenderTarget(null);
  for (const [o, m] of restore) o.material = m;
  scene.overrideMaterial = null;
  scene.background = bg;
}

function toDataURL(rgba, w, h) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  c.getContext('2d').putImageData(new ImageData(rgba, w, h), 0, 0);
  return c.toDataURL('image/png');
}

function f32ToBase64(arr) {
  const bytes = new Uint8Array(arr.buffer);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function renderPasses({ renderer, scene, camera, W, H, S = 2, idMaterials, idTable, depthRange = null }) {
  const t0 = performance.now();
  const timings = {};

  // ---- beauty
  renderer.setRenderTarget(null);
  renderer.render(scene, camera);
  const beauty = renderer.domElement.toDataURL('image/png');
  timings.beauty = performance.now() - t0;

  // ---- G-buffer at S x
  const w = W * S;
  const h = H * S;
  const opts = { depthBuffer: true, colorSpace: THREE.NoColorSpace };
  const rtDepth = new THREE.WebGLRenderTarget(w, h, { ...opts, type: THREE.FloatType });
  const rtNormal = new THREE.WebGLRenderTarget(w, h, { ...opts, type: THREE.UnsignedByteType });
  const rtId = new THREE.WebGLRenderTarget(w, h, { ...opts, type: THREE.UnsignedByteType });
  const shadows = renderer.shadowMap.enabled;
  renderer.shadowMap.enabled = false;
  renderTo(renderer, scene, camera, rtDepth, { override: depthMaterial });
  renderTo(renderer, scene, camera, rtNormal, { override: normalMaterial });
  renderTo(renderer, scene, camera, rtId, { swap: idMaterials });
  renderer.shadowMap.enabled = shadows;
  const Z = readTarget(renderer, rtDepth, Float32Array);
  const N = readTarget(renderer, rtNormal, Uint8Array);
  const I = readTarget(renderer, rtId, Uint8Array);
  for (const rt of [rtDepth, rtNormal, rtId]) rt.dispose();
  timings.gbuffer = performance.now() - t0 - timings.beauty;

  // ---- hi-res edge detection (row 0 of GL buffers is the bottom row)
  const at = (x, y) => (y * w + x);
  const edges = new Uint8Array(w * h);
  const nv = (i) => [N[i * 4] / 127.5 - 1, N[i * 4 + 1] / 127.5 - 1, N[i * 4 + 2] / 127.5 - 1];
  const differs = (a, b) => {
    const za = Z[a * 4];
    const zb = Z[b * 4];
    if ((za > 0) !== (zb > 0)) return true;
    if (za === 0) return false;
    if (I[a * 4] !== I[b * 4] || I[a * 4 + 1] !== I[b * 4 + 1] || I[a * 4 + 2] !== I[b * 4 + 2]) return true;
    if (Math.abs(za - zb) / Math.min(za, zb) > EDGE.depthRel) return true;
    const na = nv(a);
    const nb = nv(b);
    return na[0] * nb[0] + na[1] * nb[1] + na[2] * nb[2] < EDGE.normalCos;
  };
  for (let y = 0; y < h - 1; y++) {
    for (let x = 0; x < w - 1; x++) {
      const i = at(x, y);
      if (differs(i, i + 1) || differs(i, i + w)) edges[i] = 1;
    }
  }

  // ---- depth range (disparity, MiDaS-style: near = white, sky = black).
  // Default range = 2nd..98th percentile of visible depth, so a close-up floor or wall
  // doesn't eat the whole gray range; a camera can pin it with depthRange: [near, far].
  let zmin;
  let zmax;
  if (depthRange) [zmin, zmax] = depthRange;
  else {
    const zs = [];
    for (let i = 0; i < w * h; i += 7) if (Z[i * 4] > 0) zs.push(Z[i * 4]);
    zs.sort((a, b) => a - b);
    zmin = zs[Math.floor(zs.length * 0.02)];
    zmax = zs[Math.floor(zs.length * 0.98)];
  }
  const dNear = 1 / zmin;
  const dFar = 1 / zmax;
  const disparity = (z) => (z > 0 ? Math.min(1, Math.max(0, (1 / z - dFar) / (dNear - dFar))) : 0);

  // ---- box-filter down to W x H, flipping to top-down rows
  const depthPng = new Uint8ClampedArray(W * H * 4);
  const normalPng = new Uint8ClampedArray(W * H * 4);
  const linesPng = new Uint8ClampedArray(W * H * 4);
  const idPng = new Uint8ClampedArray(W * H * 4);
  const depthF32 = new Float32Array(W * H);
  const coverage = {};
  const inv = 1 / (S * S);
  for (let oy = 0; oy < H; oy++) {
    const srcY = (H - 1 - oy) * S;
    for (let ox = 0; ox < W; ox++) {
      let d = 0; let e = 0; let nr = 0; let ng = 0; let nb = 0; let zsum = 0; let zn = 0;
      for (let sy = 0; sy < S; sy++) {
        for (let sx = 0; sx < S; sx++) {
          const i = at(ox * S + sx, srcY + sy);
          const z = Z[i * 4];
          d += disparity(z);
          e += edges[i];
          if (z > 0) { nr += N[i * 4]; ng += N[i * 4 + 1]; nb += N[i * 4 + 2]; zsum += z; zn++; }
        }
      }
      const o = (oy * W + ox) * 4;
      const dv = Math.round(d * inv * 255);
      depthPng.set([dv, dv, dv, 255], o);
      const ev = Math.min(255, Math.round(e * inv * 255 * 1.6));
      linesPng.set([ev, ev, ev, 255], o);
      if (zn) normalPng.set([nr / zn, ng / zn, nb / zn, 255], o);
      else normalPng.set([128, 128, 255, 255], o);
      depthF32[oy * W + ox] = zn ? zsum / zn : 0;
      const ci = at(ox * S, srcY) * 4; // nearest sample keeps IDs exact
      idPng.set([I[ci], I[ci + 1], I[ci + 2], 255], o);
      const key = idTable[`${I[ci]},${I[ci + 1]},${I[ci + 2]}`] ?? 'sky';
      coverage[key] = (coverage[key] || 0) + 1;
    }
  }
  for (const k of Object.keys(coverage)) coverage[k] = +(coverage[k] / (W * H)).toFixed(5);
  timings.process = performance.now() - t0 - timings.beauty - timings.gbuffer;

  const info = renderer.info.render;
  return {
    beauty,
    depth: toDataURL(depthPng, W, H),
    normal: toDataURL(normalPng, W, H),
    lines: toDataURL(linesPng, W, H),
    ids: toDataURL(idPng, W, H),
    depthF32: f32ToBase64(depthF32),
    stats: {
      zmin: +zmin.toFixed(3),
      zmax: +zmax.toFixed(3),
      coverage,
      triangles: info.triangles,
      drawCalls: info.calls,
      supersample: S,
      edgeParams: { normalCreaseDeg: 35, depthRel: EDGE.depthRel },
      timingsMs: Object.fromEntries(Object.entries({ ...timings, total: performance.now() - t0 }).map(([k, v]) => [k, Math.round(v)])),
    },
  };
}
