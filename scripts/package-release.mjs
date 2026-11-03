// Builds a local release zip. Never publishes anything.
// Usage: node scripts/package-release.mjs
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, cpSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const out = join(root, 'dist-plugin');
const manifest = JSON.parse(readFileSync(join(root, 'manifest.json'), 'utf8'));
const releaseDir = join(root, 'release');
const stage = join(releaseDir, `stage-${manifest.id}`);
const zipName = `${manifest.id}-${manifest.version}.zip`;

execFileSync('npm', ['run', 'build:plugin'], { cwd: root, stdio: 'inherit' });

for (const f of ['main.js', 'manifest.json', 'styles.css', 'engine-manifest.json', 'engine/crawl_site.py']) {
  if (!existsSync(join(out, f))) throw new Error(`Missing build output: ${f}`);
}

rmSync(stage, { recursive: true, force: true });
mkdirSync(stage, { recursive: true });
for (const f of ['main.js', 'manifest.json', 'styles.css', 'engine-manifest.json']) {
  cpSync(join(out, f), join(stage, f));
}
cpSync(join(out, 'engine'), join(stage, 'engine'), {
  recursive: true,
  filter: (src) => !/__pycache__|\.pyc$/.test(src),
});

const files = [];
(function walk(dir, rel = '') {
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    const r = rel ? `${rel}/${name}` : name;
    if (statSync(p).isDirectory()) walk(p, r);
    else files.push(r);
  }
})(stage);

rmSync(join(releaseDir, zipName), { force: true });
execFileSync('zip', ['-q', '-X', '-r', join(releaseDir, zipName), ...files], { cwd: stage });
rmSync(stage, { recursive: true, force: true });

const sum = createHash('sha256').update(readFileSync(join(releaseDir, zipName))).digest('hex');
writeFileSync(join(releaseDir, `${zipName}.sha256`), `${sum}  ${zipName}\n`);
console.log(`Release: release/${zipName}\nSHA256: ${sum}\nFiles: ${files.length}`);
