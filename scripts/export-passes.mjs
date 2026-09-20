// Exports render passes (beauty, depth, normal, lines, ids + float depth) for every camera.
// Content-addressed cache: a camera is re-rendered only if the scene spec, the camera,
// the lighting or the scene source code changed.
//
//   node scripts/export-passes.mjs            # all cameras
//   node scripts/export-passes.mjs street     # one camera
//   node scripts/export-passes.mjs --force    # ignore cache
import { createServer } from 'vite';
import { chromium } from 'playwright-core';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, readdir, appendFile, access } from 'node:fs/promises';
import { join } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const OUT = join(ROOT, 'out', 'passes');
const args = process.argv.slice(2);
const force = args.includes('--force');
const only = args.filter((a, i) => !a.startsWith('--') && args[i - 1] !== '--camera');

const config = JSON.parse(await readFile(join(ROOT, 'config', 'cameras.json'), 'utf8'));
const specText = await readFile(join(ROOT, 'scene', 'house.json'), 'utf8');
const srcDir = join(ROOT, 'scene', 'src');
const srcText = (await Promise.all((await readdir(srcDir)).sort().map((f) => readFile(join(srcDir, f), 'utf8')))).join('\n');

const sha = (s) => createHash('sha256').update(s).digest('hex').slice(0, 16);
const exists = (p) => access(p).then(() => true, () => false);

function npy(f32, h, w) {
  let header = `{'descr': '<f4', 'fortran_order': False, 'shape': (${h}, ${w}), }`;
  const pad = 64 - ((10 + header.length + 1) % 64);
  header += ' '.repeat(pad) + '\n';
  const pre = Buffer.alloc(10);
  Buffer.from('\x93NUMPY', 'latin1').copy(pre, 0);
  pre[6] = 1; pre[7] = 0;
  pre.writeUInt16LE(header.length, 8);
  return Buffer.concat([pre, Buffer.from(header, 'latin1'), Buffer.from(f32, 'base64')]);
}

await mkdir(OUT, { recursive: true });
const customIdx = args.indexOf('--camera');
const custom = customIdx >= 0 ? JSON.parse(args[customIdx + 1]) : null;
const cams = custom ? [custom] : config.cameras.filter((c) => !only.length || only.includes(c.id));
const plan = cams.map((cam) => ({
  cam,
  hash: sha(JSON.stringify({ spec: specText, cam, w: config.width, h: config.height, lighting: config.lighting, src: srcText })),
}));

const todo = [];
for (const p of plan) {
  const meta = join(OUT, p.cam.id, 'meta.json');
  const hit = !force && (await exists(meta)) && JSON.parse(await readFile(meta, 'utf8')).hash === p.hash;
  if (hit) {
    console.log(`cache hit   ${p.cam.id}  ${p.hash}`);
    await appendFile(join(ROOT, 'out', 'runs.jsonl'), JSON.stringify({ ts: new Date().toISOString(), stage: 'export_passes', item: p.cam.id, hash: p.hash, cache_hit: true, ms: 0, cost_usd: 0 }) + '\n');
  } else todo.push(p);
}

if (todo.length) {
  const server = await createServer({ root: join(ROOT, 'scene'), logLevel: 'error', server: { port: 5199 } });
  await server.listen();
  const url = server.resolvedUrls.local[0];
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-angle=d3d11', '--ignore-gpu-blocklist', '--enable-gpu'] });
  const page = await browser.newPage();
  page.on('pageerror', (e) => console.error('page error:', e.message));
  await page.goto(`${url}?export=1`);
  await page.waitForFunction(() => window.__ready, null, { timeout: 60000 });
  const glRenderer = await page.evaluate(() => window.__glRenderer);
  console.log(`WebGL: ${glRenderer}`);

  for (const { cam, hash } of todo) {
    const t0 = Date.now();
    const r = await page.evaluate((id) => window.renderPasses(id), cam.id);
    const dir = join(OUT, cam.id);
    await mkdir(dir, { recursive: true });
    for (const k of ['beauty', 'depth', 'normal', 'lines', 'ids']) {
      await writeFile(join(dir, `${k}.png`), Buffer.from(r[k].split(',')[1], 'base64'));
    }
    await writeFile(join(dir, 'depth.npy'), npy(r.depthF32, config.height, config.width));
    const ms = Date.now() - t0;
    const meta = { hash, camera: cam, width: config.width, height: config.height, lighting: config.lighting, glRenderer, wallMs: ms, ...r.stats };
    await writeFile(join(dir, 'meta.json'), JSON.stringify(meta, null, 2));
    await appendFile(join(ROOT, 'out', 'runs.jsonl'), JSON.stringify({ ts: new Date().toISOString(), stage: 'export_passes', item: cam.id, hash, cache_hit: false, ms, cost_usd: 0, gl: glRenderer }) + '\n');
    console.log(`rendered    ${cam.id}  ${hash}  ${ms} ms  (${r.stats.triangles} tris, ${r.stats.drawCalls} calls)`);
  }
  await browser.close();
  await server.close();
}
