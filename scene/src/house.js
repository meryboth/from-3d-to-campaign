import * as THREE from 'three';

// Procedural house builder. Input: a house spec (house.json). Output: a THREE.Group
// where every mesh has userData.mat = semantic material key (see materials.js).

let MATS = null;

function mesh(geo, key) {
  const m = new THREE.Mesh(geo, MATS[key]);
  m.userData.mat = key;
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

// Axis-aligned box given its min corner-free description: center x/z, base y.
function box(parent, key, [cx, y0, cz], [w, h, d]) {
  const geo = new THREE.BoxGeometry(w, h, d);
  const m = mesh(geo, key);
  m.position.set(cx, y0 + h / 2, cz);
  parent.add(m);
  return m;
}

function cylinder(parent, key, [cx, y0, cz], rTop, rBot, h, seg = 12) {
  const m = mesh(new THREE.CylinderGeometry(rTop, rBot, h, seg), key);
  m.position.set(cx, y0 + h / 2, cz);
  parent.add(m);
  return m;
}

// ---------- walls with openings ----------

// Local frame of a wall: x runs along the wall (u), y up, z across the thickness.
function wallFrame(from, to) {
  const alongX = Math.abs(from[1] - to[1]) < 1e-6;
  const s0 = alongX ? Math.min(from[0], to[0]) : Math.min(from[1], to[1]);
  const s1 = alongX ? Math.max(from[0], to[0]) : Math.max(from[1], to[1]);
  const fixed = alongX ? from[1] : from[0];
  return {
    alongX, s0, len: s1 - s0, fixed,
    // local +z maps to world +z (alongX) or world -x (alongZ)
    sign: (face) => (alongX ? { '-z': -1, '+z': 1 } : { '+x': -1, '-x': 1 })[face] ?? 1,
    place(obj, along) {
      if (alongX) obj.position.set(along, 0, fixed);
      else { obj.position.set(fixed, 0, along); obj.rotation.y = -Math.PI / 2; }
      return obj;
    },
  };
}

function wallGeometry(len, h, t, openings, s0) {
  const shape = new THREE.Shape();
  shape.moveTo(0, 0);
  const doors = openings.filter((o) => !o.sill).map((o) => ({ ...o, u: o.at - s0 })).sort((a, b) => a.u - b.u);
  for (const d of doors) {
    shape.lineTo(d.u - d.w / 2, 0);
    shape.lineTo(d.u - d.w / 2, d.h);
    shape.lineTo(d.u + d.w / 2, d.h);
    shape.lineTo(d.u + d.w / 2, 0);
  }
  shape.lineTo(len, 0);
  shape.lineTo(len, h);
  shape.lineTo(0, h);
  shape.lineTo(0, 0);
  for (const o of openings.filter((p) => p.sill)) {
    const u = o.at - s0;
    const hole = new THREE.Path();
    hole.moveTo(u - o.w / 2, o.sill);
    hole.lineTo(u + o.w / 2, o.sill);
    hole.lineTo(u + o.w / 2, o.sill + o.h);
    hole.lineTo(u - o.w / 2, o.sill + o.h);
    hole.lineTo(u - o.w / 2, o.sill);
    shape.holes.push(hole);
  }
  const geo = new THREE.ExtrudeGeometry(shape, { depth: t, bevelEnabled: false });
  geo.translate(0, 0, -t / 2);
  return geo;
}

function buildWall(parent, { from, to, h, t, openings = [] }, key, opts = {}) {
  const f = wallFrame(from, to);
  const m = mesh(wallGeometry(f.len, h, t, openings, f.s0), key);
  f.place(m, f.s0);
  parent.add(m);
  for (const o of openings) {
    const g = new THREE.Group();
    fillOpening(g, o, t, f.sign(o.face), opts);
    f.place(g, o.at);
    parent.add(g);
  }
  return f;
}

// Opening infill, built in the wall's local frame centered on the opening.
// s = +1/-1: which local z side is "outside" (where shutters, grilles and moldings go).
function fillOpening(g, o, t, s, { molding = false } = {}) {
  const { w, h } = o;
  const sill = o.sill || 0;
  const out = (d) => s * (t / 2 + d); // z just proud of the outer face

  const frame = (x, y, fw, fh, z = 0, depth = 0.1, key = 'wood_door') => box(g, key, [x, y, z], [fw, fh, depth]);
  const glassPane = (x, y, gw, gh, z = 0) => box(g, 'glass', [x, y, z], [gw, gh, 0.02]);

  if (o.kind === 'window') {
    const f = 0.07;
    frame(-w / 2 + f / 2, sill, f, h);
    frame(w / 2 - f / 2, sill, f, h);
    frame(0, sill, w, f);
    frame(0, sill + h - f, w, f);
    frame(0, sill, 0.06, h); // mullion
    frame(0, sill + h * 0.72, w, 0.06); // transom
    glassPane(0, sill + f, w - 2 * f, h - 2 * f);
    box(g, molding ? 'facade_molding' : 'patio_plaster', [0, sill - 0.08, out(0.02)], [w + 0.3, 0.08, 0.2]); // sill
  }

  if (o.kind === 'door') {
    const top = o.fanlight ? h - 0.75 : h;
    const lw = w / 2;
    for (const sx of [-1, 1]) {
      const cx = sx * lw / 2;
      box(g, 'wood_door', [cx, 0, -s * 0.06], [lw - 0.02, top, 0.08]);
      for (const [py, ph] of [[0.25, top * 0.3], [top * 0.4, top * 0.52]]) {
        box(g, 'wood_door', [cx, py, -s * 0.06 + s * 0.05], [lw - 0.22, ph, 0.03]); // raised panels
      }
    }
    if (o.fanlight) {
      frame(0, top, w, 0.1);
      glassPane(0, top + 0.1, w - 0.1, 0.6);
      for (let k = -2; k <= 2; k++) box(g, 'iron', [k * w / 6, top + 0.1, 0.02 * s], [0.03, 0.6, 0.03]);
    }
  }

  if (o.kind === 'doorGlass') {
    const lw = w / 2;
    const f = 0.07;
    for (const sx of [-1, 1]) {
      const cx = sx * lw / 2;
      frame(cx - lw / 2 + f / 2, 0, f, h, 0, 0.07);
      frame(cx + lw / 2 - f / 2, 0, f, h, 0, 0.07);
      frame(cx, h - f, lw, f, 0, 0.07);
      frame(cx, 0, lw - 2 * f, h * 0.38, 0, 0.06); // lower panel
      frame(cx, h * 0.38, lw, f, 0, 0.07); // mid rail
      glassPane(cx, h * 0.38 + f, lw - 2 * f, h * 0.62 - 2 * f);
    }
  }

  if (o.grille) {
    const z = out(0.08);
    const n = Math.floor(w / 0.12);
    for (let k = 0; k <= n; k++) box(g, 'iron', [-w / 2 + (k * w) / n, sill, z], [0.022, h, 0.022]);
    for (const y of [sill + 0.12, sill + h * 0.5, sill + h - 0.12]) box(g, 'iron', [0, y, z], [w, 0.03, 0.03]);
  }

  if (o.shutters) {
    const lw = w / 2;
    const z = out(molding ? 0.09 : 0.03);
    for (const sx of [-1, 1]) {
      const leaf = box(g, 'wood_shutter', [sx * (w / 2 + (molding ? 0.16 : 0.02) + lw / 2), sill, z], [lw, h, 0.04]);
      // louvre rails give the shutter its horizontal rhythm in lines/normals
      for (let y = 0.2; y < h - 0.1; y += 0.28) {
        box(g, 'wood_shutter', [leaf.position.x, sill + y, z + s * 0.025], [lw - 0.08, 0.035, 0.015]);
      }
    }
  }

  if (molding) {
    const m = 0.15;
    box(g, 'facade_molding', [-w / 2 - m / 2, sill, out(0.025)], [m, h, 0.05]);
    box(g, 'facade_molding', [w / 2 + m / 2, sill, out(0.025)], [m, h, 0.05]);
    box(g, 'facade_molding', [0, sill + h, out(0.025)], [w + 2 * m, m, 0.05]);
    box(g, 'facade_molding', [0, sill + h + m, out(0.07)], [w + 0.5, 0.14, 0.14]); // lintel cornice
  }
}

// ---------- house parts ----------

function buildFacade(root, spec) {
  const F = spec.facade;
  const W = spec.lot.width;
  const topY = F.cornice.y + F.cornice.h;
  const zOut = F.z - F.t / 2; // street-side face
  const openings = F.openings.map((o) => ({ ...o, sill: o.sill || 0 }));
  buildWall(root, { from: [0, F.z], to: [W, F.z], h: topY, t: F.t, openings }, 'facade_plaster', { molding: true });

  // plinth, split around doors
  const doors = openings.filter((o) => !o.sill).map((o) => [o.at - o.w / 2, o.at + o.w / 2]).sort((a, b) => a[0] - b[0]);
  let x = 0;
  for (const [a, b] of [...doors, [W, W]]) {
    if (a - x > 0.01) box(root, 'facade_plinth', [(x + a) / 2, 0, zOut - 0.04], [a - x, F.plinth.h, 0.08]);
    x = b;
  }
  // door frames (the door gets its own casing instead of a molding surround)
  for (const o of openings.filter((p) => !p.sill)) {
    box(root, 'facade_molding', [o.at - o.w / 2 - 0.08, 0, zOut - 0.05], [0.16, o.h + 0.16, 0.1]);
    box(root, 'facade_molding', [o.at + o.w / 2 + 0.08, 0, zOut - 0.05], [0.16, o.h + 0.16, 0.1]);
    box(root, 'facade_molding', [o.at, o.h, zOut - 0.05], [o.w + 0.32, 0.16, 0.1]);
    box(root, 'facade_molding', [o.at, o.h + 0.16, zOut - 0.1], [o.w + 0.6, 0.14, 0.2]);
  }
  // pilasters with capitals
  for (const px of F.pilasters) {
    box(root, 'facade_molding', [px, F.plinth.h, zOut - 0.05], [0.42, F.cornice.y - F.plinth.h - 0.15, 0.1]);
    box(root, 'facade_molding', [px, F.cornice.y - 0.15, zOut - 0.08], [0.52, 0.15, 0.16]);
    box(root, 'facade_plinth', [px, 0, zOut - 0.1], [0.5, F.plinth.h, 0.2]);
  }
  // stepped cornice
  let y = F.cornice.y;
  for (const [ch, cd, extra] of [[0.12, 0.2, 0.2], [0.14, 0.32, 0.3], [0.14, 0.45, 0.4]]) {
    box(root, 'facade_molding', [W / 2, y, zOut - cd / 2 + 0.02], [W + extra, ch, cd]);
    y += ch;
  }
  // balustrade: posts, rails, balusters
  const B = F.balustrade;
  const bz = F.z;
  for (const px of B.posts) {
    box(root, 'facade_molding', [px, B.y, bz], [0.45, B.h, 0.45]);
    box(root, 'facade_molding', [px, B.y + B.h, bz], [0.55, 0.1, 0.55]);
  }
  for (let i = 0; i < B.posts.length - 1; i++) {
    const a = B.posts[i] + 0.225;
    const b = B.posts[i + 1] - 0.225;
    const cx = (a + b) / 2;
    box(root, 'facade_molding', [cx, B.y, bz], [b - a, 0.15, 0.35]);
    box(root, 'facade_molding', [cx, B.y + B.h - 0.14, bz], [b - a, 0.14, 0.4]);
    const n = Math.max(2, Math.round((b - a) / 0.22));
    for (let k = 0; k < n; k++) {
      const bx = a + ((k + 0.5) * (b - a)) / n;
      cylinder(root, 'facade_molding', [bx, B.y + 0.15, bz], 0.045, 0.065, B.h - 0.29, 10);
    }
  }
}

function buildInteriorWalls(root, spec) {
  for (const w of spec.walls) {
    const key = { party: 'party_wall', patio: 'patio_plaster', interior: 'interior_wall' }[w.kind];
    const f = buildWall(root, w, key);
    if (w.kind === 'patio') {
      // parapet above the roof line and a molding band at the eave
      const P = new THREE.Group();
      box(P, 'patio_plaster', [f.len / 2, w.h, 0], [f.len, 0.75, 0.2]);
      box(P, 'facade_molding', [f.len / 2, w.h - 0.22, 0], [f.len, 0.22, w.t + 0.16]);
      box(P, 'facade_molding', [f.len / 2, w.h + 0.75, 0], [f.len + 0.04, 0.08, 0.3]);
      f.place(P, f.s0);
      root.add(P);
    }
  }
}

function buildRoofs(root, spec) {
  for (const r of spec.rooms) {
    const [x0, x1] = r.x;
    const [z0, z1] = r.z;
    box(root, 'roof', [(x0 + x1) / 2, r.h, (z0 + z1) / 2], [x1 - x0, 0.3, z1 - z0]);
  }
  for (const g of spec.galleries) {
    const [x0, x1] = g.x;
    const [z0, z1] = g.z;
    const len = z1 - z0;
    box(root, 'gallery_roof', [(x0 + x1 + 0.2) / 2, g.h, (z0 + z1) / 2], [x1 - x0 + 0.2, 0.1, len]);
    box(root, 'iron', [x1 - 0.05, g.h - 0.24, (z0 + z1) / 2], [0.1, 0.24, len]); // beam
    for (const cz of g.columns) {
      cylinder(root, 'iron', [x1 - 0.05, 0, cz], 0.06, 0.07, g.h - 0.24, 12);
      box(root, 'iron', [x1 - 0.05, 0, cz], [0.22, 0.12, 0.22]);
      box(root, 'iron', [x1 - 0.05, g.h - 0.36, cz], [0.2, 0.12, 0.2]);
    }
  }
}

function floorPlane(parent, key, [x0, x1], [z0, z1], y = 0.01, tile = 0.6) {
  const w = x1 - x0;
  const d = z1 - z0;
  const geo = new THREE.PlaneGeometry(w, d);
  const uv = geo.attributes.uv;
  for (let i = 0; i < uv.count; i++) uv.setXY(i, (uv.getX(i) * w) / tile, (uv.getY(i) * d) / tile);
  geo.rotateX(-Math.PI / 2);
  const m = mesh(geo, key);
  m.castShadow = false;
  m.position.set((x0 + x1) / 2, y, (z0 + z1) / 2);
  parent.add(m);
  return m;
}

function tree(parent, { x, z, h, r }) {
  const trunkH = h * 0.45;
  cylinder(parent, 'trunk', [x, 0, z], 0.12 + r * 0.03, 0.2 + r * 0.04, trunkH, 10);
  const blobs = [[0, 0, 0, 1], [r * 0.45, -r * 0.15, r * 0.2, 0.7], [-r * 0.4, -r * 0.1, -r * 0.3, 0.65], [0.1, r * 0.35, -0.2, 0.6]];
  for (const [dx, dy, dz, s] of blobs) {
    const m = mesh(new THREE.IcosahedronGeometry(r * s, 2), 'foliage');
    m.scale.set(1, 0.8, 1);
    m.position.set(x + dx, trunkH + r * 0.75 + dy, z + dz);
    parent.add(m);
  }
}

function buildGarden(root, spec) {
  for (const p of spec.patios) floorPlane(root, p.floor, p.x, p.z, 0.01, p.floor === 'floor_tile' ? 0.6 : 4);
  for (const t of spec.garden.trees) tree(root, t);
  for (const p of spec.garden.planters) {
    box(root, 'planter', [p.x, 0, p.z], [0.55, 0.5, 0.55]);
    const bush = mesh(new THREE.IcosahedronGeometry(0.42, 2), 'foliage');
    bush.position.set(p.x, 0.85, p.z);
    root.add(bush);
  }
}

// ---------- street context ----------

function neighborFacadeOpenings(n) {
  const [x0, x1] = n.x;
  const width = x1 - x0;
  const fh = n.h / n.floors;
  const openings = [];
  const count = Math.max(2, Math.floor(width / 2.6));
  for (let f = 0; f < n.floors; f++) {
    for (let k = 0; k < count; k++) {
      const at = x0 + ((k + 0.5) * width) / count;
      if (f === 0 && k === count - 1) openings.push({ kind: 'door', at, w: 1.1, h: 2.6, face: '-z' });
      else openings.push({ kind: 'window', at, w: 1.1, h: Math.min(2.2, fh - 1.3), sill: f * fh + 0.9, face: '-z' });
    }
  }
  return { openings, fh, count };
}

function buildContext(root, spec) {
  const C = spec.context;
  const W = spec.lot.width;
  const span = 80;
  const cx = W / 2;
  const sw = C.street.sidewalk;
  const rw = C.street.roadway;

  const ground = mesh(new THREE.PlaneGeometry(400, 400).rotateX(-Math.PI / 2), 'ground');
  ground.position.set(cx, -0.05, 60);
  ground.castShadow = false;
  root.add(ground);

  // near sidewalk, curb, roadway, far sidewalk
  box(root, 'sidewalk', [cx, -0.05, -sw / 2], [span, 0.17, sw]);
  box(root, 'curb', [cx, -0.05, -sw - 0.08], [span, 0.17, 0.16]);
  floorPlane(root, 'asphalt', [cx - span / 2, cx + span / 2], [-sw - 0.16 - rw, -sw - 0.16], -0.04, 4);
  box(root, 'curb', [cx, -0.05, -sw - rw - 0.24], [span, 0.17, 0.16]);
  box(root, 'sidewalk', [cx, -0.05, -sw - rw - 0.32 - sw / 2], [span, 0.17, sw]);

  for (const t of C.streetTrees) {
    box(root, 'curb', [t.x, 0.1, t.z], [1.0, 0.06, 1.0]);
    tree(root, t);
  }

  for (const n of C.neighbors) {
    const [x0, x1] = n.x;
    const { openings, fh } = neighborFacadeOpenings(n);
    const fz = 0.2;
    buildWall(root, { from: [x0 + 0.02, fz], to: [x1 - 0.02, fz], h: n.h, t: 0.4, openings }, n.tone);
    box(root, n.tone, [(x0 + x1) / 2, 0, fz + 0.2 + n.depth / 2], [x1 - x0 - 0.04, n.h, n.depth]);
    box(root, n.tone, [(x0 + x1) / 2, 0, fz + n.depth + 8], [x1 - x0 - 0.04, 3.4, 16]);
    box(root, 'facade_molding', [(x0 + x1) / 2, n.h - 0.3, fz - 0.25], [x1 - x0 - 0.04, 0.3, 0.3]);
    // upper-floor balconies with iron railings
    for (let f = 1; f < n.floors; f++) {
      for (const o of openings.filter((p) => p.sill && Math.abs(p.sill - (f * fh + 0.9)) < 1e-6)) {
        const by = f * fh;
        box(root, n.tone, [o.at, by, fz - 0.65], [1.8, 0.12, 0.9]);
        box(root, 'iron', [o.at, by + 1.05, fz - 1.08], [1.8, 0.04, 0.04]);
        for (let k = 0; k <= 12; k++) box(root, 'iron', [o.at - 0.9 + (k * 1.8) / 12, by + 0.12, fz - 1.08], [0.02, 0.93, 0.02]);
      }
    }
  }
}

export function buildHouse(spec, mats) {
  MATS = mats;
  const root = new THREE.Group();
  root.name = spec.id;
  buildFacade(root, spec);
  buildInteriorWalls(root, spec);
  buildRoofs(root, spec);
  buildGarden(root, spec);
  buildContext(root, spec);
  return root;
}
