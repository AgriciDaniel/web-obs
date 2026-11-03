import { execFile } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

/** Windows installs usually provide `python`, not `python3.14`. */
export const DEFAULT_PYTHON = process.platform === 'win32' ? 'python' : 'python3.14';

function venvPythonPath(venvDir: string): string {
  return process.platform === 'win32'
    ? path.join(venvDir, 'Scripts', 'python.exe')
    : path.join(venvDir, 'bin', 'python3');
}

export function resolvePythonCandidate(
  vaultBase: string,
  engineDir: string,
  configuredBinary: string
): string {
  const trimmed = (configuredBinary || '').trim();
  if (trimmed && trimmed !== 'python3' && trimmed !== 'python' && trimmed !== 'python3.14') {
    return trimmed;
  }

  const candidates = [
    venvPythonPath(path.join(engineDir, '.venv')),
    venvPythonPath(path.join(vaultBase, 'engine', '.venv')),
    venvPythonPath(path.join(vaultBase, '.venv')),
  ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return DEFAULT_PYTHON;
}

function execFileAsync(
  cmd: string,
  args: string[],
  cwd: string,
  signal?: AbortSignal
): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve({ ok: false, stdout: '', stderr: 'Capability check cancelled.' });
      return;
    }
    try {
      execFile(cmd, args, { cwd, timeout: 20_000, maxBuffer: 64 * 1024, signal, windowsHide: true }, (err, stdout, stderr) => {
        resolve({
          ok: !err,
          stdout: String(stdout ?? ''),
          stderr: String(stderr || (err ? err.message : '')),
        });
      });
    } catch (err) {
      resolve({ ok: false, stdout: '', stderr: err instanceof Error ? err.message : 'Capability check failed.' });
    }
  });
}

type RenderMode = 'auto' | 'always' | 'never';

export interface PythonReadinessOptions {
  renderMode?: RenderMode;
  signal?: AbortSignal;
}

export interface PythonCapabilities {
  missingCore: string[];
  pythonSupported: boolean;
  playwrightAvailable: boolean;
  chromiumExecutableAvailable: boolean;
  chromiumExecutablePath?: string;
  chromiumExpectedPath?: string;
  browserError?: string;
}

// Presence checks only. Do not install packages or launch Chromium from the plugin.
const CAPABILITY_PROBE = `
import importlib, json, os, sys
sys.path.insert(0, sys.argv[2])
result = {"missingCore": [], "pythonSupported": sys.version_info >= (3, 14), "playwrightAvailable": False, "chromiumExecutableAvailable": False}
for name in ("requests", "bs4", "lxml"):
    try:
        importlib.import_module(name)
    except Exception:
        result["missingCore"].append(name)
if sys.argv[1] != "never":
    try:
        from playwright.sync_api import sync_playwright
        result["playwrightAvailable"] = True
        from browser_runtime import resolve_chromium_executable
        with sync_playwright() as driver:
            browser = resolve_chromium_executable(driver)
            result["chromiumExecutableAvailable"] = bool(browser["executablePath"])
            result["chromiumExecutablePath"] = browser["executablePath"]
            result["chromiumExpectedPath"] = browser["expectedPath"]
            result["browserError"] = browser["error"]
    except Exception as exc:
        result["browserError"] = str(exc)
print(json.dumps({"webObsCapabilities": result}))
`;

export async function probePython(pyBin: string, cwd: string, options: PythonReadinessOptions, engineDir = path.join(cwd, 'engine')): Promise<PythonCapabilities | null> {
  const res = await execFileAsync(pyBin, ['-B', '-c', CAPABILITY_PROBE, options.renderMode ?? 'never', engineDir], cwd, options.signal);
  if (!res.ok || options.signal?.aborted) return null;
  for (const line of res.stdout.trim().split(/\r?\n/).reverse()) {
    try {
      const parsed = JSON.parse(line) as { webObsCapabilities?: Partial<PythonCapabilities> };
      const value = parsed.webObsCapabilities;
      if (value && Array.isArray(value.missingCore) && value.missingCore.every((item) => typeof item === 'string') &&
          typeof value.pythonSupported === 'boolean' && typeof value.playwrightAvailable === 'boolean' &&
          typeof value.chromiumExecutableAvailable === 'boolean') {
        return value as PythonCapabilities;
      }
    } catch {
      // Ignore library startup output; accept only the structured capability record.
    }
  }
  return null;
}

export async function checkPythonDeps(pyBin: string, cwd: string, options: PythonReadinessOptions = {}): Promise<boolean> {
  const capabilities = await probePython(pyBin, cwd, options);
  return capabilities !== null && capabilities.pythonSupported && capabilities.missingCore.length === 0 &&
    ((options.renderMode ?? 'never') === 'never' || (capabilities.playwrightAvailable && capabilities.chromiumExecutableAvailable));
}

export async function ensurePythonEngineReady(
  vaultBase: string,
  scriptPath: string,
  configuredBinary: string,
  onStatus?: (message: string) => void,
  options: PythonReadinessOptions = {}
): Promise<{ pythonBin: string; error?: string }> {
  const engineDir = path.dirname(scriptPath);
  const candidate = resolvePythonCandidate(vaultBase, engineDir, configuredBinary);

  if (options.signal?.aborted) {
    return { pythonBin: candidate, error: 'Capability check cancelled.' };
  }
  onStatus?.('Checking local Python and selected rendering capabilities...');
  const capabilities = await probePython(candidate, vaultBase, options, engineDir);
  if (options.signal?.aborted) return { pythonBin: candidate, error: 'Capability check cancelled.' };
  if (!capabilities) {
    return {
      pythonBin: candidate,
      error: `Could not check the Python runtime (${candidate}). Configure a working Python 3.14+ environment in settings. Nothing was installed automatically.`,
    };
  }
  if (!capabilities.pythonSupported || capabilities.missingCore.length > 0) {
    return {
      pythonBin: candidate,
      error: `Python 3.14+ with requests, beautifulsoup4 and lxml is required (${candidate}). Prepare the engine requirements manually in your chosen source environment, then select its Python executable. Nothing was installed automatically.`,
    };
  }
  if ((options.renderMode ?? 'never') !== 'never' && (!capabilities.playwrightAvailable || !capabilities.chromiumExecutableAvailable)) {
    return {
      pythonBin: candidate,
      error: !capabilities.playwrightAvailable
        ? `The selected Python environment has no usable Playwright module (${candidate}). Nothing was installed automatically.`
        : capabilities.browserError || `Compatible Chromium was not found for ${candidate}. The default and standard user caches were checked. Nothing was installed automatically.`,
    };
  }
  return { pythonBin: candidate };
}

export async function pythonVersionOf(pyBin: string, cwd: string, signal?: AbortSignal): Promise<string | null> {
  const res = await execFileAsync(pyBin, ['-B', '-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])'], cwd, signal);
  const line = res.stdout.trim().split(/\r?\n/).pop() ?? '';
  return res.ok && /^\d+\.\d+/.test(line) ? line : null;
}
