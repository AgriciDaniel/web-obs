import crypto from 'node:crypto';
import fs from 'node:fs';
import https from 'node:https';
import path from 'node:path';
import { buildDoctorReport, type DoctorFacts, type DoctorRow } from './doctorReport';
import { probePython, pythonVersionOf, resolvePythonCandidate } from './pythonRuntime';

export interface DoctorContext {
  vaultBase: string | null;
  pluginDir: string;
  pluginVersion: string;
  pythonBinary: string;
  renderMode: 'auto' | 'always' | 'never';
}

function sha256(file: string): string {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function locateEngine(ctx: DoctorContext): string | null {
  if (!ctx.vaultBase) return null;
  for (const dir of [path.join(ctx.vaultBase, ctx.pluginDir, 'engine'), path.join(ctx.vaultBase, 'engine')]) {
    if (fs.existsSync(path.join(dir, 'crawl_site.py'))) return dir;
  }
  return null;
}

function engineMismatches(engineDir: string, pluginAbs: string): string[] | null {
  const manifestPath = path.join(pluginAbs, 'engine-manifest.json');
  if (path.dirname(engineDir) !== pluginAbs || !fs.existsSync(manifestPath)) return null;
  try {
    const files = (JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as { files?: Record<string, string> }).files;
    if (!files) return null;
    const bad: string[] = [];
    for (const [name, hash] of Object.entries(files)) {
      const target = path.join(engineDir, name);
      if (!fs.existsSync(target) || sha256(target) !== hash) bad.push(name);
    }
    return bad;
  } catch {
    return null;
  }
}

function engineVersionOf(engineDir: string): string | null {
  try {
    const match = /__version__\s*=\s*["']([^"']+)["']/.exec(fs.readFileSync(path.join(engineDir, '__init__.py'), 'utf8'));
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

function checkWritable(vaultBase: string): boolean {
  const probe = path.join(vaultBase, `.web-obs-doctor-${process.pid}-${Date.now()}.tmp`);
  try {
    fs.writeFileSync(probe, 'ok');
    fs.rmSync(probe, { force: true });
    return true;
  } catch {
    try { fs.rmSync(probe, { force: true }); } catch { /* nothing to clean */ }
    return false;
  }
}

function checkNetwork(timeoutMs = 6000): Promise<{ ok: boolean; detail: string }> {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value: { ok: boolean; detail: string }) => {
      if (!done) { done = true; resolve(value); }
    };
    try {
      const req = https.request('https://example.com/', { method: 'HEAD', timeout: timeoutMs }, (res) => {
        res.resume();
        finish({ ok: true, detail: `Outbound HTTPS works (example.com answered ${res.statusCode ?? 'OK'}).` });
      });
      req.on('timeout', () => { req.destroy(); finish({ ok: false, detail: 'Outbound HTTPS timed out.' }); });
      req.on('error', (err) => finish({ ok: false, detail: `Outbound HTTPS failed: ${err.message}` }));
      req.end();
    } catch (err) {
      finish({ ok: false, detail: err instanceof Error ? err.message : 'Outbound HTTPS failed.' });
    }
  });
}

export async function runDoctor(ctx: DoctorContext): Promise<DoctorRow[]> {
  const engineDir = locateEngine(ctx);
  const pluginAbs = ctx.vaultBase ? path.join(ctx.vaultBase, ctx.pluginDir) : '';
  const pythonBin = resolvePythonCandidate(ctx.vaultBase ?? '.', engineDir ?? '', ctx.pythonBinary);
  const cwd = ctx.vaultBase ?? '.';

  const pythonVersion = await pythonVersionOf(pythonBin, cwd);
  const caps = pythonVersion && engineDir
    ? await probePython(pythonBin, cwd, { renderMode: ctx.renderMode }, engineDir)
    : null;
  const network = await checkNetwork();

  const facts: DoctorFacts = {
    desktopVault: ctx.vaultBase !== null,
    pluginVersion: ctx.pluginVersion,
    engineFound: engineDir !== null,
    engineVersion: engineDir ? engineVersionOf(engineDir) : null,
    engineMismatches: engineDir ? engineMismatches(engineDir, pluginAbs) : null,
    pythonBin,
    pythonVersion,
    missingCore: caps ? caps.missingCore : null,
    renderMode: ctx.renderMode,
    playwrightAvailable: caps ? caps.playwrightAvailable : null,
    chromiumAvailable: caps ? caps.chromiumExecutableAvailable : null,
    browserError: caps?.browserError ?? null,
    vaultWritable: ctx.vaultBase ? checkWritable(ctx.vaultBase) : null,
    network,
    optionalPackages: caps?.optionalPackages ?? null,
  };
  return buildDoctorReport(facts);
}
