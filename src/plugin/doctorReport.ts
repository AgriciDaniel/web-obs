// Pure diagnostics logic. No Obsidian or Node imports, so it can be unit tested in isolation.

export type DoctorState = 'pass' | 'warn' | 'fail';

export interface DoctorRow {
  id: string;
  label: string;
  state: DoctorState;
  detail: string;
  fix?: string;
}

export interface DoctorFacts {
  desktopVault: boolean;
  pluginVersion: string;
  engineFound: boolean;
  engineVersion: string | null;
  /** Files listed in engine-manifest.json that are missing or have a different hash. */
  engineMismatches: string[] | null;
  pythonBin: string;
  pythonVersion: string | null;
  missingCore: string[] | null;
  renderMode: 'auto' | 'always' | 'never';
  playwrightAvailable: boolean | null;
  chromiumAvailable: boolean | null;
  browserError: string | null;
  vaultWritable: boolean | null;
  network: { ok: boolean; detail: string } | null;
  /** Optional packages by pip name. Missing ones only switch off their own check. Absent on older probes. */
  optionalPackages?: Record<string, boolean> | null;
}

/** Optional Python packages and the check each one enables. */
export const OPTIONAL_PACKAGES: Array<{ name: string; feature: string }> = [
  { name: 'dnspython', feature: 'email DNS checks' },
  { name: 'pyspellchecker', feature: 'spell check' },
  { name: 'html5lib', feature: 'HTML parse error counts' },
];

const DEFAULT_FIX_PYTHON =
  'Create a Python 3.14+ environment with the engine requirements, then set its executable in Web-Obs settings.';

export function parsePythonVersion(text: string): { major: number; minor: number } | null {
  const match = /(\d+)\.(\d+)/.exec(text);
  return match ? { major: Number(match[1]), minor: Number(match[2]) } : null;
}

export function buildDoctorReport(f: DoctorFacts): DoctorRow[] {
  const rows: DoctorRow[] = [];

  rows.push(
    f.desktopVault
      ? { id: 'vault', label: 'Desktop vault', state: 'pass', detail: 'A local folder vault is open.' }
      : {
          id: 'vault',
          label: 'Desktop vault',
          state: 'fail',
          detail: 'The vault is not on a local filesystem.',
          fix: 'Web-Obs needs a local desktop vault. Open it with Obsidian desktop.',
        }
  );

  if (!f.engineFound) {
    rows.push({
      id: 'engine',
      label: 'Engine files',
      state: 'fail',
      detail: 'engine/crawl_site.py was not found in the plugin folder.',
      fix: 'Restart Obsidian so Web-Obs can unpack its engine. If that fails, check that the plugin folder is writable.',
    });
  } else if (f.engineMismatches === null) {
    rows.push({
      id: 'engine',
      label: 'Engine files',
      state: 'warn',
      detail: 'Engine present, but engine-manifest.json could not be read to verify it.',
      fix: 'Restart Obsidian. Web-Obs restores its engine files on start.',
    });
  } else if (f.engineMismatches.length > 0) {
    const shown = f.engineMismatches.slice(0, 4).join(', ');
    const more = f.engineMismatches.length > 4 ? ` and ${f.engineMismatches.length - 4} more` : '';
    rows.push({
      id: 'engine',
      label: 'Engine files',
      state: 'fail',
      detail: `Missing or changed: ${shown}${more}.`,
      fix: 'The install is partial or stale. Restart Obsidian. Web-Obs restores its engine files on start.',
    });
  } else {
    rows.push({ id: 'engine', label: 'Engine files', state: 'pass', detail: 'All engine files match the packaged manifest.' });
  }

  if (f.engineFound && f.engineVersion !== null && f.engineVersion !== f.pluginVersion) {
    rows.push({
      id: 'version',
      label: 'Version match',
      state: 'warn',
      detail: `Plugin ${f.pluginVersion} but engine ${f.engineVersion}.`,
      fix: 'Restart Obsidian so the engine matches the plugin.',
    });
  } else {
    rows.push({
      id: 'version',
      label: 'Version match',
      state: 'pass',
      detail: f.engineVersion ? `Plugin and engine are ${f.pluginVersion}.` : `Plugin ${f.pluginVersion}.`,
    });
  }

  const parsed = f.pythonVersion ? parsePythonVersion(f.pythonVersion) : null;
  if (!f.pythonVersion || !parsed) {
    rows.push({
      id: 'python',
      label: 'Python',
      state: 'fail',
      detail: `Could not run ${f.pythonBin}.`,
      fix: DEFAULT_FIX_PYTHON,
    });
  } else if (parsed.major < 3 || (parsed.major === 3 && parsed.minor < 14)) {
    rows.push({
      id: 'python',
      label: 'Python',
      state: 'fail',
      detail: `${f.pythonBin} is ${parsed.major}.${parsed.minor}, the engine needs 3.14 or newer.`,
      fix: DEFAULT_FIX_PYTHON,
    });
  } else {
    rows.push({ id: 'python', label: 'Python', state: 'pass', detail: `${f.pythonBin} is ${parsed.major}.${parsed.minor}.` });
  }

  if (f.missingCore === null) {
    rows.push({
      id: 'packages',
      label: 'Python packages',
      state: 'fail',
      detail: 'The capability check did not return a result.',
      fix: 'Confirm the Python executable runs, then use Check Engine in settings.',
    });
  } else if (f.missingCore.length > 0) {
    rows.push({
      id: 'packages',
      label: 'Python packages',
      state: 'fail',
      detail: `Missing: ${f.missingCore.join(', ')}.`,
      fix: 'Run pip install requests beautifulsoup4 lxml in the selected environment. Web-Obs never installs packages itself.',
    });
  } else {
    rows.push({ id: 'packages', label: 'Python packages', state: 'pass', detail: 'requests, beautifulsoup4 and lxml are available.' });
  }

  if (f.optionalPackages) {
    // Informational only: a missing optional package never warns or fails diagnostics.
    const missing = OPTIONAL_PACKAGES.filter((entry) => f.optionalPackages?.[entry.name] !== true);
    rows.push({
      id: 'optional',
      label: 'Optional packages',
      state: 'pass',
      detail: missing.length === 0
        ? 'dnspython, pyspellchecker and html5lib are available.'
        : `Optional, not installed: ${missing.map((entry) => `${entry.name} (${entry.feature})`).join(', ')}. Those checks are skipped.`,
    });
  }

  if (f.renderMode === 'never') {
    rows.push({ id: 'browser', label: 'Headless browser', state: 'pass', detail: 'Not needed: rendering is set to fast HTTP only.' });
  } else if (f.playwrightAvailable === false) {
    rows.push({
      id: 'browser',
      label: 'Headless browser',
      state: f.renderMode === 'always' ? 'fail' : 'warn',
      detail: 'Playwright is not installed in this environment.',
      fix:
        f.renderMode === 'always'
          ? 'Install Playwright and Chromium, or switch rendering to Auto or fast HTTP only.'
          : 'Single page apps will fall back to the fast HTTP capture. Install Playwright to render them.',
    });
  } else if (f.chromiumAvailable === false) {
    rows.push({
      id: 'browser',
      label: 'Headless browser',
      state: f.renderMode === 'always' ? 'fail' : 'warn',
      detail: f.browserError || 'Compatible Chromium was not found.',
      fix: 'Run "playwright install chromium" in the selected environment.',
    });
  } else if (f.playwrightAvailable === null || f.chromiumAvailable === null) {
    rows.push({ id: 'browser', label: 'Headless browser', state: 'warn', detail: 'Could not be checked.' });
  } else {
    rows.push({ id: 'browser', label: 'Headless browser', state: 'pass', detail: 'Playwright and Chromium are available.' });
  }

  if (f.vaultWritable === null) {
    rows.push({ id: 'write', label: 'Vault write access', state: 'warn', detail: 'Could not be checked.' });
  } else if (!f.vaultWritable) {
    rows.push({
      id: 'write',
      label: 'Vault write access',
      state: 'fail',
      detail: 'Web-Obs cannot write to the vault folder.',
      fix: 'Check folder permissions. In a Flatpak or sandbox, grant Obsidian access to the vault location.',
    });
  } else {
    rows.push({ id: 'write', label: 'Vault write access', state: 'pass', detail: 'Captures can be written to the vault.' });
  }

  if (f.network === null) {
    rows.push({ id: 'network', label: 'Network', state: 'warn', detail: 'Not checked.' });
  } else if (!f.network.ok) {
    rows.push({
      id: 'network',
      label: 'Network',
      state: 'warn',
      detail: f.network.detail,
      fix: 'Check your connection, VPN or proxy. Captures need outbound HTTPS.',
    });
  } else {
    rows.push({ id: 'network', label: 'Network', state: 'pass', detail: f.network.detail });
  }

  return rows;
}

export function summarizeDoctor(rows: DoctorRow[]): { state: DoctorState; failures: number; warnings: number; headline: string } {
  const failures = rows.filter((r) => r.state === 'fail').length;
  const warnings = rows.filter((r) => r.state === 'warn').length;
  if (failures > 0) {
    return { state: 'fail', failures, warnings, headline: `${failures} problem${failures === 1 ? '' : 's'} will stop captures.` };
  }
  if (warnings > 0) {
    return { state: 'warn', failures, warnings, headline: `Ready, with ${warnings} note${warnings === 1 ? '' : 's'}.` };
  }
  return { state: 'pass', failures, warnings, headline: 'Everything needed for captures is ready.' };
}

export function doctorReportText(rows: DoctorRow[]): string {
  const mark: Record<DoctorState, string> = { pass: 'PASS', warn: 'WARN', fail: 'FAIL' };
  const lines = rows.map((r) => `${mark[r.state]}  ${r.label}: ${r.detail}${r.fix ? `\n      Fix: ${r.fix}` : ''}`);
  return `Web-Obs diagnostics\n${lines.join('\n')}`;
}
