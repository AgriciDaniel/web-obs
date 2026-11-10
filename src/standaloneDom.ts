/**
 * Obsidian provides createEl, createDiv and createSpan as globals, and the shared map components use them. The
 * standalone browser app has no Obsidian, so it installs the same three helpers (the subset Web-Obs uses: a class
 * name and text) when App loads. Inside Obsidian the real helpers are already there and are left untouched.
 */
type StandaloneInfo = { cls?: string | string[]; text?: string };

function standaloneCreateEl(tag: string, o?: StandaloneInfo | string): HTMLElement {
  const el = document.createElement(tag);
  const info = typeof o === 'string' ? { cls: o } : o;
  if (info?.cls) el.className = Array.isArray(info.cls) ? info.cls.join(' ') : info.cls;
  if (info?.text !== undefined) el.textContent = info.text;
  return el;
}

function installStandaloneDomHelpers(): void {
  const host = window as unknown as { createEl?: unknown; createDiv?: unknown; createSpan?: unknown };
  host.createEl ??= standaloneCreateEl;
  host.createDiv ??= (o?: StandaloneInfo | string) => standaloneCreateEl('div', o);
  host.createSpan ??= (o?: StandaloneInfo | string) => standaloneCreateEl('span', o);
}

installStandaloneDomHelpers();
