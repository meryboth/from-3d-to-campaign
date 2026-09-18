import * as THREE from 'three';

// Every mesh carries a semantic material key (mesh.userData.mat). The key drives
// the beauty look here and the flat color in the material-ID pass.
// `id` colors are raw 8-bit RGB written straight to the ID map (no color management).
export const MATERIALS = {
  facade_plaster: { id: [230, 25, 75], color: '#d8c6a4', roughness: 0.9 },
  facade_molding: { id: [245, 130, 48], color: '#e9dcc2', roughness: 0.85 },
  facade_plinth: { id: [255, 225, 25], color: '#8f877b', roughness: 0.95 },
  patio_plaster: { id: [210, 245, 60], color: '#e7dcc8', roughness: 0.92 },
  party_wall: { id: [60, 180, 75], color: '#c9b9a0', roughness: 0.95 },
  interior_wall: { id: [0, 128, 128], color: '#efe8da', roughness: 0.95 },
  roof: { id: [70, 240, 240], color: '#a99c88', roughness: 0.98 },
  gallery_roof: { id: [0, 130, 200], color: '#7d8084', roughness: 0.7, metalness: 0.3 },
  wood_door: { id: [145, 30, 180], color: '#5b3a24', roughness: 0.7 },
  wood_shutter: { id: [240, 50, 230], color: '#4d6a4c', roughness: 0.75 },
  glass: { id: [250, 190, 212], color: '#27343b', roughness: 0.08, metalness: 0.7 },
  iron: { id: [128, 0, 0], color: '#1d1d1f', roughness: 0.45, metalness: 0.6 },
  floor_tile: { id: [170, 110, 40], color: '#ffffff', roughness: 0.55, map: 'damero' },
  grass: { id: [0, 190, 0], color: '#6d8747', roughness: 1 },
  foliage: { id: [0, 90, 20], color: '#4a6a36', roughness: 0.9 },
  trunk: { id: [110, 70, 40], color: '#5a4a3b', roughness: 1 },
  planter: { id: [255, 160, 120], color: '#a3593a', roughness: 0.9 },
  sidewalk: { id: [255, 250, 200], color: '#bdb6a8', roughness: 0.95 },
  curb: { id: [128, 128, 0], color: '#8c8880', roughness: 0.95 },
  asphalt: { id: [0, 0, 128], color: '#3c3e41', roughness: 0.9 },
  ground: { id: [128, 128, 128], color: '#8c8574', roughness: 1 },
  neighbor_a: { id: [220, 190, 255], color: '#cdc4b5', roughness: 0.92 },
  neighbor_b: { id: [170, 255, 195], color: '#b9a488', roughness: 0.92 },
  neighbor_c: { id: [255, 215, 180], color: '#d9d1c1', roughness: 0.92 },
};

export const SKY_ID = [0, 0, 0];

function damero() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = '#e9e4d8';
  g.fillRect(0, 0, 128, 128);
  g.fillStyle = '#222222';
  g.fillRect(0, 0, 64, 64);
  g.fillRect(64, 64, 64, 64);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

export function createMaterials() {
  const out = {};
  for (const [key, m] of Object.entries(MATERIALS)) {
    out[key] = new THREE.MeshStandardMaterial({
      color: m.color,
      roughness: m.roughness,
      metalness: m.metalness ?? 0,
      map: m.map === 'damero' ? damero() : null,
    });
  }
  return out;
}

export function createIdMaterials() {
  const out = {};
  for (const [key, m] of Object.entries(MATERIALS)) {
    const color = new THREE.Color().setRGB(m.id[0] / 255, m.id[1] / 255, m.id[2] / 255, THREE.LinearSRGBColorSpace);
    out[key] = new THREE.MeshBasicMaterial({ color, toneMapped: false });
  }
  return out;
}
