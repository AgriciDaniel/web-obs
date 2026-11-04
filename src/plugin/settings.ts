import path from 'node:path';
import {
  type App,
  FileSystemAdapter,
  Notice,
  type Plugin,
  PluginSettingTab,
  Setting,
} from 'obsidian';
import type { GlobeViewMode } from '../types/site';
import { ensurePythonEngineReady } from './pythonRuntime';

export interface WebObsPluginSettings {
  pythonBinary: string;
  defaultMaxPages: number;
  downloadImages: boolean;
  imageMode: 'preferred' | 'all';
  renderMode: 'auto' | 'always' | 'never';
  browserAudit: boolean;
  pageSnapshots: boolean;
  snapshotLimit: number;
  snapshotHtml: boolean;
  spellCheck: boolean;
  dnsChecks: boolean;
  defaultViewMode: GlobeViewMode;
  themeBehavior: 'obsidian' | 'dark' | 'light';
  openInSplitPane: boolean;
  syncActiveNote: boolean;
}

export const DEFAULT_WEB_OBS_SETTINGS: WebObsPluginSettings = {
  pythonBinary: 'python3.14',
  defaultMaxPages: 250,
  downloadImages: true,
  imageMode: 'preferred',
  renderMode: 'auto',
  browserAudit: true,
  pageSnapshots: true,
  snapshotLimit: 25,
  snapshotHtml: false,
  spellCheck: false,
  dnsChecks: true,
  defaultViewMode: 'globe',
  themeBehavior: 'obsidian',
  openInSplitPane: true,
  syncActiveNote: true,
};

interface SettingTabBridge {
  settings: WebObsPluginSettings;
  saveSettings: () => Promise<void>;
  notifySettingsChanged: () => void;
}

export class WebObsSettingTab extends PluginSettingTab {
  private bridge: SettingTabBridge;
  private pluginRef: Plugin;

  constructor(app: App, plugin: Plugin, bridge: SettingTabBridge) {
    super(app, plugin);
    this.pluginRef = plugin;
    this.bridge = bridge;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl('h2', { text: 'Web-Obs Site Globe' });

    new Setting(containerEl)
      .setName('Python executable')
      .setDesc('Python 3.14+ binary used to run the bundled website crawler engine.')
      .addText((text) =>
        text
          .setPlaceholder('python3.14')
          .setValue(this.bridge.settings.pythonBinary)
          .onChange(async (value) => {
            this.bridge.settings.pythonBinary = value.trim() || 'python3.14';
            await this.bridge.saveSettings();
          })
      )
      .addButton((btn) =>
        btn.setButtonText('Run diagnostics').onClick(() => {
          (this.pluginRef as unknown as { openDiagnostics?: () => void }).openDiagnostics?.();
        })
      )
      .addButton((btn) =>
        btn.setButtonText('Check Engine').onClick(async () => {
          const adapter = this.app.vault.adapter;
          const vaultBase = adapter instanceof FileSystemAdapter ? adapter.getBasePath() : '.';
          const scriptPath = path.join(
            vaultBase,
            this.pluginRef.manifest.dir ?? '.obsidian/plugins/web-obs',
            'engine',
            'crawl_site.py'
          );
          btn.setDisabled(true);
          try {
            const ready = await ensurePythonEngineReady(
              vaultBase,
              scriptPath,
              this.bridge.settings.pythonBinary || 'python3.14',
              undefined,
              { renderMode: this.bridge.settings.renderMode }
            );
            new Notice(ready.error ?? `Web-Obs local engine dependencies are available (${ready.pythonBin}).`);
          } finally {
            btn.setDisabled(false);
          }
        })
      );

    new Setting(containerEl)
      .setName('Max pages per capture')
      .setDesc('Maximum internal pages crawled per website capture.')
      .addSlider((slider) =>
        slider
          .setLimits(20, 500, 10)
          .setValue(this.bridge.settings.defaultMaxPages)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.bridge.settings.defaultMaxPages = value;
            await this.bridge.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName('Download images locally')
      .setDesc('Saves page images into sites/<domain>/assets/ so notes work offline.')
      .addToggle((toggle) =>
        toggle
          .setValue(this.bridge.settings.downloadImages)
          .onChange(async (value) => {
            this.bridge.settings.downloadImages = value;
            await this.bridge.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName('Image variants')
      .setDesc('Preferred saves primary images, posters and icons. All also archives responsive variants. Both retain every observed URL in the inventory.')
      .addDropdown((drop) => drop
        .addOption('preferred', 'Preferred images (Recommended)')
        .addOption('all', 'All image variants')
        .setValue(this.bridge.settings.imageMode ?? 'preferred')
        .onChange(async (value) => {
          this.bridge.settings.imageMode = value === 'all' ? 'all' : 'preferred';
          await this.bridge.saveSettings();
        }));

    new Setting(containerEl)
      .setName('JavaScript / SPA rendering')
      .setDesc('Auto uses fast HTTP first and launches Playwright only for SPA shells.')
      .addDropdown((drop) =>
        drop
          .addOption('auto', 'Auto (Recommended)')
          .addOption('never', 'Fast HTTP only')
          .addOption('always', 'Always headless render')
          .setValue(this.bridge.settings.renderMode)
          .onChange(async (value) => {
            this.bridge.settings.renderMode = value as 'auto' | 'always' | 'never';
            await this.bridge.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName('Browser audit sample')
      .setDesc('Opens up to five pages in the headless browser after capture for lab timings, automated accessibility rules (axe-core), screenshots, JavaScript dependence and third parties on first load. Needs Playwright and Chromium; skipped with Fast HTTP only.')
      .addToggle((toggle) =>
        toggle.setValue(this.bridge.settings.browserAudit ?? true).onChange(async (value) => {
          this.bridge.settings.browserAudit = value;
          await this.bridge.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName('Page snapshots')
      .setDesc('Saves a full-page screenshot of the most important pages after capture and shows it at the top of each note. Needs Playwright and Chromium; skipped with Fast HTTP only.')
      .addToggle((toggle) =>
        toggle.setValue(this.bridge.settings.pageSnapshots ?? true).onChange(async (value) => {
          this.bridge.settings.pageSnapshots = value;
          await this.bridge.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName('Snapshot limit')
      .setDesc('Most pages to snapshot per capture, home and the strongest pages first. Keeps capture time and vault size in check (about 0.3 to 1 MB per snapshot).')
      .addText((text) =>
        text.setValue(String(this.bridge.settings.snapshotLimit ?? 25)).onChange(async (value) => {
          const parsed = Number.parseInt(value, 10);
          if (Number.isInteger(parsed) && parsed >= 1 && parsed <= 500) {
            this.bridge.settings.snapshotLimit = parsed;
            await this.bridge.saveSettings();
          }
        })
      );

    new Setting(containerEl)
      .setName('Save rendered HTML with snapshots')
      .setDesc('Also keeps the page HTML after JavaScript ran, next to each snapshot. Useful for comparing what crawlers and visitors see.')
      .addToggle((toggle) =>
        toggle.setValue(this.bridge.settings.snapshotHtml ?? false).onChange(async (value) => {
          this.bridge.settings.snapshotHtml = value;
          await this.bridge.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName('Email DNS checks')
      .setDesc('Looks up MX, SPF, DMARC, common DKIM selectors and CAA for the domain through your system DNS resolver. Needs the optional dnspython package.')
      .addToggle((toggle) =>
        toggle.setValue(this.bridge.settings.dnsChecks ?? true).onChange(async (value) => {
          this.bridge.settings.dnsChecks = value;
          await this.bridge.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName('Spell check')
      .setDesc('Lists possible English misspellings per page. Names and jargon show up too, so it is off by default. Needs the optional pyspellchecker package.')
      .addToggle((toggle) =>
        toggle.setValue(this.bridge.settings.spellCheck ?? false).onChange(async (value) => {
          this.bridge.settings.spellCheck = value;
          await this.bridge.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName('Default 3D layout')
      .setDesc('Initial layout when opening Web-Obs.')
      .addDropdown((drop) =>
        drop
          .addOption('globe', 'Site Globe (3D Sphere)')
          .addOption('road', 'Sitemap Road (Click Depth)')
          .addOption('clusters', 'Link Clusters (Force)')
          .setValue(this.bridge.settings.defaultViewMode)
          .onChange(async (value) => {
            this.bridge.settings.defaultViewMode = value as GlobeViewMode;
            await this.bridge.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName('Theme')
      .setDesc('Follow Obsidian theme or force Dark / Light.')
      .addDropdown((drop) =>
        drop
          .addOption('obsidian', 'Follow Obsidian')
          .addOption('dark', 'Dark')
          .addOption('light', 'Light')
          .setValue(this.bridge.settings.themeBehavior)
          .onChange(async (value) => {
            this.bridge.settings.themeBehavior = value as 'obsidian' | 'dark' | 'light';
            await this.bridge.saveSettings();
            this.bridge.notifySettingsChanged();
          })
      );

    new Setting(containerEl)
      .setName('Open notes in split pane')
      .setDesc('Keep the 3D Site Globe visible beside opened Markdown notes.')
      .addToggle((toggle) =>
        toggle
          .setValue(this.bridge.settings.openInSplitPane)
          .onChange(async (value) => {
            this.bridge.settings.openInSplitPane = value;
            await this.bridge.saveSettings();
          })
      );
  }
}
