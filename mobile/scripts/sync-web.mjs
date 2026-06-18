/* ============================================================================
 * sync-web.mjs — Genera `mobile/www/` a partir de la PWA compartida.
 * Copia webui/mobile + el shim webui/remote, reescribe rutas relativas y
 * añade native.js. Ejecuta antes de `cap sync`.  ─  node scripts/sync-web.mjs
 * ========================================================================== */
import { promises as fs } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, '..');                 // mobile/
const REPO = path.resolve(ROOT, '..');                 // themeforge/
const SRC = path.join(REPO, 'webui', 'mobile');
const SHIM = path.join(REPO, 'webui', 'remote', 'tfbridge-remote.js');
const WWW = path.join(ROOT, 'www');

const FILES = ['index.html', 'app.jsx', 'manifest.webmanifest', 'sw.js', 'icon-192.png', 'icon-512.png'];

async function main() {
  await fs.rm(WWW, { recursive: true, force: true });
  await fs.mkdir(path.join(WWW, 'remote'), { recursive: true });

  for (const f of FILES) {
    await fs.copyFile(path.join(SRC, f), path.join(WWW, f));
  }
  await fs.copyFile(SHIM, path.join(WWW, 'remote', 'tfbridge-remote.js'));
  await fs.copyFile(path.join(ROOT, 'native.js'), path.join(WWW, 'native.js'));

  // index.html: rutas relativas + inyectar native.js tras el shim.
  let html = await fs.readFile(path.join(WWW, 'index.html'), 'utf8');
  html = html.replace('../remote/tfbridge-remote.js', 'remote/tfbridge-remote.js');
  html = html.replace(
    '<script src="remote/tfbridge-remote.js"></script>',
    '<script src="remote/tfbridge-remote.js"></script>\n  <script src="native.js"></script>'
  );
  await fs.writeFile(path.join(WWW, 'index.html'), html);

  // sw.js: el shim ahora cuelga de remote/ (no ../remote/).
  let sw = await fs.readFile(path.join(WWW, 'sw.js'), 'utf8');
  sw = sw.replace("'../remote/tfbridge-remote.js'", "'remote/tfbridge-remote.js'");
  await fs.writeFile(path.join(WWW, 'sw.js'), sw);

  console.log('✓ www/ generado:', FILES.length + 2, 'archivos →', WWW);
}

main().catch((e) => { console.error('sync-web falló:', e); process.exit(1); });
