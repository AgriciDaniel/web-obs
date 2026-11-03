// The Python engine is packed into main.js at build time. Obsidian's installer only delivers
// main.js, manifest.json and styles.css, so on load we unpack the engine next to them.
// Files are written only when missing or different, so a normal start writes nothing.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

declare const __WEB_OBS_ENGINE_BUNDLE__: string | undefined;

export interface EngineBundle {
  schemaVersion: 1;
  /** Relative posix path to base64 file contents. */
  files: Record<string, string>;
}

export interface EngineInstallResult {
  state: 'ok' | 'installed' | 'repaired' | 'unavailable';
  written: string[];
}

export function decodeEngineBundle(encoded: string): EngineBundle {
  const parsed = JSON.parse(zlib.gunzipSync(Buffer.from(encoded, 'base64')).toString('utf8')) as EngineBundle;
  if (parsed.schemaVersion !== 1 || typeof parsed.files !== 'object' || parsed.files === null) {
    throw new Error('Unrecognized engine bundle format.');
  }
  return parsed;
}

function safeTarget(engineDir: string, relative: string): string {
  const normalized = path.posix.normalize(relative);
  if (!relative || path.isAbsolute(relative) || normalized.startsWith('..') || relative.includes('\\') || relative.includes('\0')) {
    throw new Error(`Refusing to write outside the engine folder: ${relative}`);
  }
  const target = path.join(engineDir, ...normalized.split('/'));
  if (!target.startsWith(engineDir + path.sep)) throw new Error(`Refusing to write outside the engine folder: ${relative}`);
  return target;
}

const sha256 = (data: Buffer): string => crypto.createHash('sha256').update(data).digest('hex');

export function installEngine(pluginDir: string, encoded: string | undefined = typeof __WEB_OBS_ENGINE_BUNDLE__ === 'string' ? __WEB_OBS_ENGINE_BUNDLE__ : undefined): EngineInstallResult {
  if (!encoded) return { state: 'unavailable', written: [] };
  const bundle = decodeEngineBundle(encoded);
  const engineDir = path.join(pluginDir, 'engine');
  const hashes: Record<string, string> = {};
  const written: string[] = [];
  let hadAnything = fs.existsSync(path.join(engineDir, 'crawl_site.py'));
  for (const relative of Object.keys(bundle.files).sort()) {
    const data = Buffer.from(bundle.files[relative], 'base64');
    hashes[relative] = sha256(data);
    const target = safeTarget(engineDir, relative);
    let current: Buffer | null = null;
    try {
      current = fs.readFileSync(target);
    } catch {
      current = null;
    }
    if (current && sha256(current) === hashes[relative]) continue;
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const temporary = `${target}.web-obs-tmp`;
    fs.writeFileSync(temporary, data);
    fs.renameSync(temporary, target);
    written.push(relative);
  }
  const manifest = JSON.stringify({ schemaVersion: 1, files: hashes }, null, 2) + '\n';
  const manifestPath = path.join(pluginDir, 'engine-manifest.json');
  let currentManifest = '';
  try {
    currentManifest = fs.readFileSync(manifestPath, 'utf8');
  } catch {
    currentManifest = '';
  }
  // Remove only files an earlier release shipped that this one no longer does. Anything else stays.
  const removed: string[] = [];
  try {
    const previous = (JSON.parse(currentManifest) as { files?: Record<string, string> }).files ?? {};
    for (const relative of Object.keys(previous)) {
      if (relative in hashes) continue;
      try {
        const target = safeTarget(engineDir, relative);
        if (sha256(fs.readFileSync(target)) === previous[relative]) {
          fs.rmSync(target);
          removed.push(relative);
        }
      } catch {
        // Already gone, edited by the user, or an unsafe name in an old manifest: leave it alone.
      }
    }
  } catch {
    // No readable previous manifest.
  }
  if (currentManifest !== manifest) fs.writeFileSync(manifestPath, manifest);
  if (removed.length > 0) written.push(...removed.map((name) => `-${name}`));
  if (written.length === 0) return { state: 'ok', written };
  hadAnything = hadAnything && written.length < Object.keys(bundle.files).length;
  return { state: hadAnything ? 'repaired' : 'installed', written };
}
