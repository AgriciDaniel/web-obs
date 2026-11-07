import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import process from 'node:process';

/** Lets the engine be cancelled through standard input; it also stops if Obsidian quits. */
export const CANCEL_ON_STDIN = '--cancel-on-stdin';

/**
 * Ask the engine to stop and clean up. Windows has no SIGTERM: there Node's kill() ends the
 * process at once, so the engine reads "cancel" on standard input instead.
 */
export function askEngineToStop(child: ChildProcessWithoutNullStreams): void {
  if (process.platform === 'win32') {
    child.stdin.once('error', () => { /* The engine may already have exited. */ });
    try { child.stdin.end('cancel\n'); } catch { /* The engine may already have exited. */ }
    return;
  }
  try { child.kill('SIGTERM'); } catch { /* The child may have failed to spawn. */ }
}

/**
 * End the engine and what it started. On Windows kill() ends only the Python process and leaves
 * its workers and browsers running, so taskkill ends the whole tree.
 */
export function forceEngineStop(child: ChildProcessWithoutNullStreams): void {
  if (process.platform === 'win32' && child.pid) {
    try {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      killer.once('error', () => { try { child.kill(); } catch { /* Already gone. */ } });
      return;
    } catch { /* Fall back to ending the Python process alone. */ }
  }
  try { child.kill('SIGKILL'); } catch { /* The child may already have exited. */ }
}
