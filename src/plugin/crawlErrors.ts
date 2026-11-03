// Turns raw engine failures (Python tracebacks, spawn errors) into short messages with a next step.
// Pure, so it can be unit tested without Obsidian.

const DIAGNOSTICS_HINT = 'Run "Web-Obs: Run diagnostics" from the command palette for a full check.';

export function friendlyEngineError(raw: string, exitInfo = ''): string {
  const text = raw.trim();
  if (!text) return `${exitInfo || 'The crawler stopped without a message.'} ${DIAGNOSTICS_HINT}`.trim();

  const missing = /ModuleNotFoundError: No module named '([^']+)'/.exec(text) ?? /ImportError: .*'([^']+)'/.exec(text);
  if (missing) {
    return `The Python environment is missing "${missing[1].split('.')[0]}". Run pip install requests beautifulsoup4 lxml in it. ${DIAGNOSTICS_HINT}`;
  }
  if (/PermissionError|EACCES|Read-only file system|\[Errno 13\]|\[Errno 30\]/.test(text)) {
    return `Web-Obs could not write to the vault. Check folder permissions or sandbox access. ${DIAGNOSTICS_HINT}`;
  }
  if (/No space left on device|\[Errno 28\]/.test(text)) {
    return 'The disk is full, so the capture could not be saved. Free some space and capture again.';
  }
  if (/SyntaxError|requires Python|Python 3\.\d+ or newer/.test(text)) {
    return `The selected Python is too old for the engine (3.14 or newer is required). ${DIAGNOSTICS_HINT}`;
  }
  if (/Traceback \(most recent call last\)/.test(text)) {
    const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const last = lines[lines.length - 1] ?? 'unknown error';
    return `The crawler hit an unexpected error: ${last.slice(0, 220)}. ${DIAGNOSTICS_HINT}`;
  }
  return text.slice(-480);
}

export function friendlySpawnError(pythonBin: string, message: string): string {
  if (/ENOENT/.test(message)) {
    return `Python was not found at "${pythonBin}". Set the correct executable in Web-Obs settings. ${DIAGNOSTICS_HINT}`;
  }
  if (/EACCES/.test(message)) {
    return `Python at "${pythonBin}" is not executable. ${DIAGNOSTICS_HINT}`;
  }
  return `Failed to start Python (${pythonBin}): ${message}. ${DIAGNOSTICS_HINT}`;
}
