// Where the publish secrets come from. No Obsidian import here, so it can be tested on its own.
//
// Order: Obsidian's own secret storage, then what was typed earlier this session (memory only), then, for the ingest secret only,
// a prompt. The secret never goes into data.json or the vault. Nothing here writes to disk.
import { SECRET_NAMES, type SecretName } from './publishTarget';

/** The part of Obsidian's `app.secretStorage` that is used (Obsidian 1.11.4 and later). */
export interface SecretStore {
  getSecret(id: string): string | null;
  setSecret(id: string, secret: string): void;
}

export interface SecretProviderOptions {
  /** `app.secretStorage`, or null/undefined on an Obsidian that does not have it. */
  store?: SecretStore | null;
  /** Memory for this session only; lives and dies with the plugin. */
  session: Map<string, string>;
  /** Asks the user for the ingest secret. Returns null if they cancel. */
  ask?: (name: SecretName) => Promise<string | null>;
}

export function makeSecretProvider(o: SecretProviderOptions): (name: SecretName) => Promise<string | null> {
  return async (name) => {
    try { const v = o.store?.getSecret(name); if (v) return v; } catch { /* storage unavailable: fall through */ }
    const kept = o.session.get(name);
    if (kept) return kept;
    if (name !== SECRET_NAMES.ingest || !o.ask) return null; // the Cloudflare values are optional: never prompted for
    const typed = (await o.ask(name))?.trim();
    if (!typed) return null;
    o.session.set(name, typed);
    return typed;
  };
}

/** Saves a value typed in the settings into Obsidian's storage. An empty value clears nothing it cannot clear: it stores an empty string. */
export function saveSecret(store: SecretStore | null | undefined, name: SecretName, value: string): boolean {
  if (!store) return false;
  try { store.setSecret(name, value); return true; } catch { return false; }
}
