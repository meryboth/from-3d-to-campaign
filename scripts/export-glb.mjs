// Exports the procedural house as a GLB so ComfyUI's Load3D node can drive the pipeline.
//   node scripts/export-glb.mjs [outfile]
import { createServer } from 'vite';
import { chromium } from 'playwright-core';
import { writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const out = process.argv[2] || join(ROOT, 'out', 'model', 'casa-chorizo.glb');

const server = await createServer({ root: join(ROOT, 'scene'), logLevel: 'error', server: { port: 5200 } });
await server.listen();
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-angle=d3d11'] });
const page = await browser.newPage();
page.on('pageerror', (e) => console.error('page error:', e.message));
await page.goto(`${server.resolvedUrls.local[0]}?export=1`);
await page.waitForFunction(() => window.__ready, null, { timeout: 60000 });
const b64 = await page.evaluate(() => window.exportGLB());
await mkdir(dirname(out), { recursive: true });
await writeFile(out, Buffer.from(b64, 'base64'));
console.log(`${out}  ${(Buffer.from(b64, 'base64').length / 1e6).toFixed(2)} MB`);
await browser.close();
await server.close();
