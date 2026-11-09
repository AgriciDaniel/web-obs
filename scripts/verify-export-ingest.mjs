// A report written by the plugin's OWN exporter (from the synthetic demo site) must pass the report server's ingest, and then be served.
// This catches a contract check that is correct on hand-made fixtures but too strict (or too loose) for what the exporter really writes.
// It imports the server code from the report app repo (apps/server); set REPORT_SERVER_DIR to that folder, otherwise the check is skipped. Synthetic data only; loopback only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';

const serverDir = path.resolve(process.env.REPORT_SERVER_DIR || '../web-obs-client-report/apps/server');
if (!fs.existsSync(path.join(serverDir, 'ingest', 'ingest.mjs'))) { console.log(`Export-to-ingest check SKIPPED: ${serverDir} not found (set REPORT_SERVER_DIR).`); process.exit(0); }

async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}
const { exportClientReport } = await load('src/report/exportAudit.ts');
const { parsePublishTarget, publishToTarget } = await load('src/plugin/publishTarget.ts');
const { PREVIEW_SITE_MANIFEST } = await load('src/data/demoSite.ts');
const { createIngestServer } = await import(pathToFileURL(path.join(serverDir, 'ingest', 'ingest.mjs')).href);
const { checkIncomingReport } = await import(pathToFileURL(path.join(serverDir, 'ingest', 'contract-check.mjs')).href);
const { createServer } = await import(pathToFileURL(path.join(serverDir, 'server.mjs')).href);

const manifest = structuredClone(PREVIEW_SITE_MANIFEST);
const exported = await exportClientReport(manifest, { approvedBy: 'Test Approver', feedbackTo: 'feedback@agency.example' });
const without = await exportClientReport(manifest, { approvedBy: 'Test Approver' });
assert.deepEqual(checkIncomingReport(JSON.parse(exported.json)), [], 'the checker finds no problem in the exporter output');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-export-ingest-'));
const reportsDir = path.join(tmp, 'reports'), registryDir = path.join(tmp, 'registry');
fs.mkdirSync(reportsDir); fs.mkdirSync(registryDir);
fs.writeFileSync(path.join(tmp, 'app.html'), '<html></html>');
const SECRET = 'export-ingest-secret-' + 'x'.repeat(30);
const ing = createIngestServer({ enabled: true, secret: SECRET, reportsDir, registryDir, auditLog: path.join(tmp, 'audit.log'), publicBase: 'https://audit.example.test', requireHttps: false, trustProxy: false, deniedDelayMs: 0, requireAccessHeader: false, acknowledgeNoEdgeAuth: true });
await new Promise((r) => ing.server.listen(0, '127.0.0.1', r));
const view = createServer({ reportsDir, registryDir, appFile: path.join(tmp, 'app.html'), outboxDir: path.join(tmp, 'outbox'), trustProxy: true, deniedDelayMs: 0 });
await new Promise((r) => view.server.listen(0, '127.0.0.1', r));
const H = { 'x-forwarded-proto': 'https', 'cf-connecting-ip': '203.0.113.5' };
try {
  for (const [name, r] of [['with a feedback address', exported], ['without one', without]]) {
    const target = parsePublishTarget(`http://127.0.0.1:${ing.server.address().port}`);
    // Exercise the plugin's real Node HTTP transport, with edge authentication disabled only on these loopback servers.
    const body = await publishToTarget(target, r.json, { hours: 72, deps: { secret: () => SECRET } });
    assert.match(body.link, /^https:\/\/audit\.example\.test\/r\//, `the ingest accepts the exporter output ${name}`);
    const token = body.link.split('/r/')[1];
    const served = await fetch(`http://127.0.0.1:${view.server.address().port}/api/r/${token}/report.json`, { headers: H });
    assert.equal(served.status, 200, `and the viewer server serves it ${name}`);
    assert.equal((await served.json()).format, 'webobs.client-report');
  }
} finally {
  await new Promise((r) => ing.server.close(r)); await new Promise((r) => view.server.close(r));
  fs.rmSync(tmp, { recursive: true, force: true });
}
console.log('Export-to-ingest OK: a report written by the plugin exporter from the synthetic demo site is accepted by the ingest (201) and served by the viewer server.');
