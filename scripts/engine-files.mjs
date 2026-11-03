import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export function engineFileHashes(root) {
  const result = {};
  function visit(relative = '') {
    for (const entry of fs.readdirSync(path.join(root, relative), { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (['.venv', '__pycache__', '.pytest_cache'].includes(entry.name) || entry.name.endsWith('.pyc')) continue;
      const file = path.posix.join(relative, entry.name);
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile()) result[file] = crypto.createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex');
      else throw new Error(`Unexpected symlink or special file in packaged engine: ${file}`);
    }
  }
  visit();
  return result;
}

export function pythonCommand(root) {
  if (process.env.WEB_OBS_PYTHON_BIN) return process.env.WEB_OBS_PYTHON_BIN;
  const local = path.join(root, 'engine', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python3');
  return fs.existsSync(local) ? local : (process.platform === 'win32' ? 'python' : 'python3');
}
