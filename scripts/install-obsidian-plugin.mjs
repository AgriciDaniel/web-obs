#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const args = process.argv.slice(2);
let vaultPath = '';
let enableInConfig = false;

for (let i = 0; i < args.length; i += 1) {
  if (args[i] === '--vault' && args[i + 1]) {
    vaultPath = path.resolve(args[i + 1]);
    i += 1;
  } else if (args[i] === '--enable') {
    enableInConfig = true;
  }
}

if (!vaultPath) {
  console.error(
    'Usage: node scripts/install-obsidian-plugin.mjs --vault "/path/to/Vault" [--enable]'
  );
  process.exit(1);
}

const obsidianDir = path.join(vaultPath, '.obsidian');
if (!fs.existsSync(obsidianDir)) {
  console.error(`Error: "${obsidianDir}" does not exist.`);
  process.exit(1);
}

const distPluginDir = path.resolve('./dist-plugin');
if (!fs.existsSync(path.join(distPluginDir, 'main.js'))) {
  console.error('Error: dist-plugin/main.js not found. Run "npm run build:plugin" first.');
  process.exit(1);
}

function copyRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const item of fs.readdirSync(src, { withFileTypes: true })) {
    if (item.name === '.venv' || item.name === '__pycache__') continue;
    const s = path.join(src, item.name);
    const d = path.join(dest, item.name);
    if (item.isDirectory()) {
      copyRecursive(s, d);
    } else {
      fs.copyFileSync(s, d);
    }
  }
}

const targetPluginDir = path.join(obsidianDir, 'plugins', 'web-obs');
// Start clean so a renamed or deleted engine file cannot linger in the vault.
fs.rmSync(path.join(targetPluginDir, 'engine'), { recursive: true, force: true });
copyRecursive(distPluginDir, targetPluginDir);
console.log(`Installed plugin files -> ${targetPluginDir}`);

if (enableInConfig) {
  const communityPluginsPath = path.join(obsidianDir, 'community-plugins.json');
  let list = [];
  if (fs.existsSync(communityPluginsPath)) {
    const backupPath = `${communityPluginsPath}.bak`;
    fs.copyFileSync(communityPluginsPath, backupPath);
    console.log(`Backed up existing config -> ${backupPath}`);
    list = JSON.parse(fs.readFileSync(communityPluginsPath, 'utf8'));
  }
  if (!list.includes('web-obs')) {
    list.push('web-obs');
    fs.writeFileSync(communityPluginsPath, `${JSON.stringify(list, null, 2)}\n`, 'utf8');
    console.log(`Enabled "web-obs" in ${communityPluginsPath}`);
  } else {
    console.log(`"web-obs" is already enabled in ${communityPluginsPath}`);
  }
}
