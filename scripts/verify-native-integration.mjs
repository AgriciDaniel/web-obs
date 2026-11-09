/** Native acceptance through Obsidian Control Center in an explicitly disposable Web-Obs test vault. */
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const arg = (name) => { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] : null; };
const configFile = path.resolve(arg('--config') ?? '.web-obs/NO-CONFIG');
const center = arg('--control-center');
const serverRoot = arg('--report-server');
assert.ok(center && serverRoot, 'Supply --control-center and --report-server source directories.');
const root = path.dirname(configFile);
const repo = path.resolve('.');
assert.ok(root.startsWith(path.join(repo, '.web-obs', 'native-review-')), 'Use a disposable native-review directory inside this checkout.');
const importFile = (base, file) => import(pathToFileURL(path.join(base, file)).href);
const { loadConfig } = await importFile(center, 'src/config.mjs');
const { Control } = await importFile(center, 'src/control.mjs');
const { invoke } = await importFile(center, 'src/tools.mjs');
const config = await loadConfig(configFile);
assert.equal(config.vaultPath, path.join(root, 'vault'), 'Refusing an unexpected vault.');
const run = fs.mkdtempSync(path.join(root, 'run-'));
config.artifactDir = path.join(run, 'screenshots');
const control = new Control(config);
const results = [];
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const record = () => fs.writeFileSync(path.join(run, 'results.json'), JSON.stringify(results, null, 2) + '\n');
const call = async (name, args = {}) => {
  const value = await invoke(control, name, args);
  if (name === 'obsidian_screenshot') { const { data, ...metadata } = value; return metadata; }
  return value;
};
const evaluate = (code) => control.exclusive(() => control.transport.evaluate(code));
const wait = (selector, text) => call('obsidian_wait_for', { selector, ...(text ? { text } : {}), timeoutMs: 10000 });
const click = async (selector) => { await call('obsidian_inspect', { selector, limit: 5 }); await call('obsidian_click', { target: { selector } }); };
const type = async (selector, text) => call('obsidian_type', { target: { selector }, text });
const stage = async (name, work) => {
  try { const evidence = await work(); results.push({ name, status: 'PASS', evidence }); record(); console.log('[PASS]', name); }
  catch (error) { let screenshot; try { screenshot = await call('obsidian_screenshot'); } catch {} results.push({ name, status: 'FAIL', error: error.message, screenshot }); record(); throw error; }
};
const plugin = "app.plugins.plugins['web-obs']";
const setSettings = async (values) => evaluate(`Object.assign(${plugin}.settings,${JSON.stringify(values)});await ${plugin}.saveSettings();return true;`);
const publishForm = async () => {
  await click('[aria-label="Publish audit"]');
  await wait('[role="dialog"][aria-label="Publish audit"]');
  await type('.wo-audit-confirm input', 'Synthetic Approver');
  await click('.wo-audit-confirm .is-primary');
};
let ingestion, viewer;
try {
  await stage('Control Center binds the exact disposable vault and running Obsidian version', async () => {
    const status = await call('obsidian_status');
    assert.equal(status.path, config.vaultPath);
    await call('obsidian_inspect', { selector: 'button,.modal-title', limit: 15 });
    return status;
  });
  await stage('The exact rebuilt plugin enables and renders in native Obsidian', async () => {
    await control.transport.cdp('Emulation.clearDeviceMetricsOverride', {});
    for (let attempt = 0; attempt < 4; attempt++) {
      const modal = await call('obsidian_inspect', { selector: '.modal-container', limit: 5 });
      if (!modal.total) break;
      await call('obsidian_press_key', { key: 'Escape' });
      await delay(250);
    }
    await evaluate("app.setting.close();window.electronWindow?.focus();delete require('process').env.WEBOBS_INGEST_SECRET;localStorage.removeItem('web-obs:node-look');await app.plugins.disablePlugin('web-obs');return true;");
    await delay(350);
    const install = path.join(config.vaultPath, '.obsidian/plugins/web-obs');
    fs.cpSync(path.join(repo, 'dist-plugin'), install, { recursive: true });
    const seed = path.join(root, 'seed-sites');
    fs.mkdirSync(seed, { recursive: true });
    for (const domain of ['native-review.test', 'second-review.test']) {
      const active = path.join(config.vaultPath, 'sites', domain), retained = path.join(seed, domain);
      if (!fs.existsSync(retained)) {
        let source = active;
        if (!fs.existsSync(source)) {
          const trash = path.join(config.vaultPath, '.web-obs/trash');
          source = path.join(trash, fs.readdirSync(trash).find((name) => name.startsWith(domain + '-')), 'sites');
        }
        fs.cpSync(source, retained, { recursive: true });
      }
      fs.cpSync(retained, active, { recursive: true });
    }
    await evaluate("await app.plugins.enablePlugin('web-obs');for(const leaf of app.workspace.getLeavesOfType('web-obs-site-globe'))leaf.detach();await app.workspace.changeLayout({main:{id:'review-main',type:'split',direction:'vertical',children:[{id:'review-leaf',type:'leaf',state:{type:'empty',state:{}}}]}});app.commands.executeCommandById('web-obs:open-site-globe');return true;");
    await control.transport.cdp('Page.bringToFront', {});
    await setSettings({ pythonBinary: path.join(repo, 'engine/.venv/bin/python3'), renderMode: 'never', browserAudit: false, pageSnapshots: false, dnsChecks: false, downloadImages: false, openInSplitPane: false, clientApproverName: '', clientReportsFolder: '', publishTarget: '', publishEnvSecrets: false });
    await wait('.wo-canvas-stage canvas');
    await evaluate("for(const leaf of app.workspace.getLeavesOfType('web-obs-site-globe'))leaf.view.dispatchCommand({type:'reload-sites',selectSiteId:'native-review.test'});return true;");
    for (let attempt = 0; attempt < 30; attempt++) {
      if (await evaluate("return document.querySelector('[aria-label=\"Captured websites\"]')?.value === 'native-review.test';")) break;
      await delay(100);
    }
    assert.equal(await evaluate("return document.querySelector('[aria-label=\"Captured websites\"]')?.value;"), 'native-review.test');
    const hash = crypto.createHash('sha256').update(fs.readFileSync(path.join(install, 'main.js'))).digest('hex');
    assert.equal(hash, crypto.createHash('sha256').update(fs.readFileSync('dist-plugin/main.js')).digest('hex'));
    return { hash, screenshot: await call('obsidian_screenshot') };
  });
  await stage('A real destination modal saves an approved allowlisted report locally', async () => {
    await click('.wo-shell [aria-label="Site audit"]');
    await publishForm();
    await wait('.modal-title', 'Where should this report go?');
    const fields = await call('obsidian_inspect', { selector: '.modal-container input[type="text"]', limit: 5 });
    await type(fields.elements[0].selector, path.join(run, 'exports'));
    await click('.modal-container button.mod-cta');
    await wait('.wo-audit-confirm', 'Client report created');
    const files = fs.readdirSync(path.join(run, 'exports'));
    assert.equal(files.length, 1);
    const json = fs.readFileSync(path.join(run, 'exports', files[0]), 'utf8');
    const report = JSON.parse(json);
    assert.equal(report.meta.review.state, 'approved');
    assert.equal(report.meta.review.reviewedBy, 'Synthetic Approver');
    assert.ok(!json.includes('obsidianPath') && !json.includes('PRIVATE-VAULT-LOGO'));
    return { findings: report.findings.length, screenshot: await call('obsidian_screenshot') };
  });
  await click('.wo-audit-confirm .wo-audit-close');

  const { createServer } = await importFile(serverRoot, 'server.mjs');
  const { createIngestServer } = await importFile(serverRoot, 'ingest/ingest.mjs');
  for (const dir of ['reports', 'registry']) fs.mkdirSync(path.join(run, dir));
  fs.writeFileSync(path.join(run, 'app.html'), '<html><body>Synthetic viewer fixture</body></html>');
  viewer = createServer({ reportsDir: path.join(run, 'reports'), registryDir: path.join(run, 'registry'), appFile: path.join(run, 'app.html'), outboxDir: path.join(run, 'outbox'), requireHttps: false, trustProxy: false, deniedDelayMs: 0 });
  await new Promise((resolve) => viewer.server.listen(0, '127.0.0.1', resolve));
  const viewerBase = `http://127.0.0.1:${viewer.server.address().port}`;
  const secret = crypto.randomBytes(32).toString('hex');
  ingestion = createIngestServer({ enabled: true, secret, reportsDir: path.join(run, 'reports'), registryDir: path.join(run, 'registry'), auditLog: path.join(run, 'ingest.log'), publicBase: viewerBase, requireHttps: false, trustProxy: false, requireAccessHeader: false, acknowledgeNoEdgeAuth: true, deniedDelayMs: 0 });
  await new Promise((resolve) => ingestion.server.listen(0, '127.0.0.1', resolve));
  const target = `http://127.0.0.1:${ingestion.server.address().port}`;
  await stage('Environment opt-in publishes through native plugin HTTP and viewer retrieval', async () => {
    await evaluate(`require('process').env.WEBOBS_INGEST_SECRET=${JSON.stringify(secret)};return true;`);
    await setSettings({ publishTarget: target, publishEnvSecrets: true });
    await publishForm();
    await delay(500);
    const prompt = await evaluate("return document.querySelector('.modal-title')?.textContent ?? null;");
    assert.notEqual(prompt, 'Publish secret', 'An explicit environment secret must be used before prompting.');
    await wait('.wo-audit-confirm', 'Client report published');
    const link = await evaluate("return document.querySelector('.wo-audit-confirm-link a')?.href;");
    assert.ok(link?.startsWith(viewerBase + '/r/'));
    const token = new URL(link).pathname.split('/r/')[1];
    const response = await fetch(viewerBase + '/api/r/' + token + '/report.json');
    assert.equal(response.status, 200);
    const report = await response.json();
    assert.equal(report.format, 'webobs.client-report');
    const settingsFile = fs.readFileSync(path.join(config.vaultPath, '.obsidian/plugins/web-obs/data.json'), 'utf8');
    assert.ok(!settingsFile.includes(secret), 'The secret never enters plugin settings.');
    return { retrievalStatus: response.status, screenshot: await call('obsidian_screenshot') };
  });
  await click('.wo-audit-confirm .wo-audit-close');
  await stage('Native Obsidian secret storage takes priority and keeps credentials out of settings', async () => {
    const available = await evaluate('return !!app.secretStorage;');
    assert.ok(available, 'This native acceptance profile must support Obsidian secret storage.');
    await evaluate(`app.secretStorage.setSecret('web-obs-publish-ingest-secret',${JSON.stringify(secret)});require('process').env.WEBOBS_INGEST_SECRET='synthetic-wrong-secret';return true;`);
    await publishForm();
    await wait('.wo-audit-confirm', 'Client report published');
    const saved = fs.readFileSync(path.join(config.vaultPath, '.obsidian/plugins/web-obs/data.json'), 'utf8');
    assert.ok(!saved.includes(secret));
    await evaluate("app.secretStorage.setSecret('web-obs-publish-ingest-secret','');return true;");
    return { screenshot: await call('obsidian_screenshot') };
  });
  await click('.wo-audit-confirm .wo-audit-close');
  await stage('Wrong credentials produce an actionable native error without a second upload', async () => {
    const before = fs.readdirSync(path.join(run, 'reports')).length;
    await evaluate("require('process').env.WEBOBS_INGEST_SECRET='synthetic-wrong-secret';return true;");
    await publishForm();
    await wait('.wo-audit-confirm [role="alert"]', 'HTTP 404');
    assert.equal(fs.readdirSync(path.join(run, 'reports')).length, before);
    return { screenshot: await call('obsidian_screenshot') };
  });
  await click('.wo-audit-confirm .wo-audit-close');
  await stage('Missing native publish credentials can be cancelled without uploading', async () => {
    const before = fs.readdirSync(path.join(run, 'reports')).length;
    await setSettings({ publishEnvSecrets: false });
    await evaluate("delete require('process').env.WEBOBS_INGEST_SECRET;return true;");
    await publishForm();
    await wait('.modal-title', 'Publish secret');
    const buttons = await call('obsidian_inspect', { selector: '.modal-container button', limit: 10 });
    await click(buttons.elements.find((b) => b.text === 'Cancel').selector);
    await wait('.wo-audit-confirm [role="alert"]', 'No ingest secret');
    assert.equal(fs.readdirSync(path.join(run, 'reports')).length, before);
    return { screenshot: await call('obsidian_screenshot') };
  });
  await click('.wo-audit-confirm .wo-audit-close');
  await setSettings({ publishTarget: '', publishEnvSecrets: false });
  await evaluate("delete require('process').env.WEBOBS_INGEST_SECRET;return true;");
  await click('[aria-label="Close audit"]');
  await stage('Native Globe, Road, Clusters and optional translucent appearance work', async () => {
    for (const mode of ['road', 'clusters', 'globe']) {
      await click(`.wo-view-tab[aria-label="${mode}"]`).catch(async () => {
        const tabs = await call('obsidian_inspect', { selector: '.wo-shell [role="tab"]', limit: 6 });
        const tab = tabs.elements.find((item) => item.text.toLowerCase() === mode);
        assert.ok(tab, mode); await click(tab.selector);
      });
      await wait('.wo-node-pill');
    }
    await click('[aria-label="Map layers"]');
    const menu = await call('obsidian_wait_for', { selector: '[role="menuitemcheckbox"]', text: 'Translucent orbs', timeoutMs: 5000 });
    await click(menu.elements[0].selector);
    await call('obsidian_press_key', { key: 'Escape' });
    assert.equal(await evaluate("return localStorage.getItem('web-obs:node-look');"), 'translucent');
    return { screenshot: await call('obsidian_screenshot') };
  });
  await stage('Archive updates every open view and preserves the other site', async () => {
    await evaluate("const first=app.workspace.getLeavesOfType('web-obs-site-globe')[0];first.view.containerEl.dataset.nativeLeaf='first';const leaf=app.workspace.getLeaf('split');await leaf.setViewState({type:'web-obs-site-globe',active:true});leaf.view.containerEl.dataset.nativeLeaf='second';app.workspace.setActiveLeaf(first,{focus:true});return true;");
    await wait('[data-native-leaf="second"] .wo-shell');
    const primary = '[data-native-leaf="first"] ';
    await click(primary + '[aria-label="Site audit"]');
    await click(primary + '[aria-label="Archive audit"]');
    await wait(primary + '[role="alertdialog"]');
    await call('obsidian_scroll', { target: { selector: primary + '.wo-audit-actionbar' }, deltaY: 600 });
    await type(primary + '[aria-label="Type the site name to confirm"]', 'native-review.test');
    await click(primary + '.is-danger');
    await delay(1000);
    assert.ok(!fs.existsSync(path.join(config.vaultPath, 'sites/native-review.test')));
    assert.ok(fs.existsSync(path.join(config.vaultPath, 'sites/second-review.test/_site-graph.json')));
    const views = await evaluate("return app.workspace.getLeavesOfType('web-obs-site-globe').map(l=>({siteId:l.view.latestManifestCache?.siteId,options:[...l.view.containerEl.querySelectorAll('[aria-label=\"Captured websites\"] option')].map(o=>o.value)}));");
    assert.ok(views.every((v) => v.siteId !== 'native-review.test' && !v.options.includes('native-review.test')), JSON.stringify(views));
    return { views, screenshot: await call('obsidian_screenshot') };
  });
  await stage('Archive restore instructions recover the exact synthetic capture bytes', async () => {
    const trash = path.join(config.vaultPath, '.web-obs/trash');
    const entries = fs.readdirSync(trash).filter((name) => name.startsWith('native-review.test-')).sort();
    const archived = path.join(trash, entries.at(-1));
    assert.ok(fs.readFileSync(path.join(archived, 'REMOVED.txt'), 'utf8').includes('sites/native-review.test'));
    const original = fs.readFileSync(path.join(root, 'seed-sites/native-review.test/_site-graph.json'));
    assert.deepEqual(fs.readFileSync(path.join(archived, 'sites/_site-graph.json')), original);
    fs.renameSync(path.join(archived, 'sites'), path.join(config.vaultPath, 'sites/native-review.test'));
    assert.deepEqual(fs.readFileSync(path.join(config.vaultPath, 'sites/native-review.test/_site-graph.json')), original);
    return { restored: true };
  });
  await stage('Four native close and reopen cycles release the view DOM and recreate one canvas', async () => {
    const samples = [];
    for (let i = 0; i < 4; i++) {
      await evaluate("for(const leaf of app.workspace.getLeavesOfType('web-obs-site-globe'))leaf.detach();return true;");
      await delay(200);
      assert.equal(await evaluate("return document.querySelectorAll('.wo-shell').length;"), 0);
      await call('obsidian_run_command', { id: 'web-obs:open-site-globe' });
      await wait('.wo-canvas-stage canvas');
      const count = await evaluate("return document.querySelectorAll('.wo-canvas-stage canvas').length;");
      assert.equal(count, 1);
      samples.push(count);
    }
    return { canvasCounts: samples, screenshot: await call('obsidian_screenshot'), heapAndGpuMemory: 'not measured' };
  });
  await stage('Native workspace layout restoration reopens the registered view', async () => {
    await evaluate("const layout=app.workspace.getLayout();await app.workspace.changeLayout(layout);return true;");
    await wait('.wo-canvas-stage canvas');
    assert.equal(await evaluate("return app.workspace.getLeavesOfType('web-obs-site-globe').length;"), 1);
    return { screenshot: await call('obsidian_screenshot') };
  });
  await stage('Native settings render the report controls with empty password inputs', async () => {
    const settings = await evaluate("app.setting.open();app.setting.openTabById('web-obs');await new Promise(r=>setTimeout(r,750));const root=app.setting.modalEl;return {labels:[...root.querySelectorAll('.setting-item-name')].map(e=>e.textContent),passwords:[...root.querySelectorAll('input[type=password]')].map(e=>({empty:e.value==='',autocomplete:e.autocomplete}))};");
    assert.ok(settings.labels.includes('Client reports') && settings.labels.includes('Publish secret'));
    assert.equal(settings.passwords.length, 3);
    assert.ok(settings.passwords.every((field) => field.empty && field.autocomplete === 'off'));
    await evaluate('app.setting.close();window.electronWindow?.focus();return true;');
    return settings;
  });
  console.log('Native integration passed. Evidence:', run);
} finally {
  for (const host of [ingestion, viewer]) if (host) await new Promise((resolve) => host.server.close(resolve));
  console.log('Native evidence:', run);
}
