import path from 'node:path';
import {
  type App,
  FileSystemAdapter,
  Notice,
  type Plugin,
  PluginSettingTab,
  Setting,
  type SettingDefinitionItem,
} from 'obsidian';
import type { GlobeViewMode } from '../types/site';
import { ensurePythonEngineReady } from './pythonRuntime';
import { SECRET_NAMES, type SecretName } from './publishTarget';
import { DEFAULT_LOOK_PREFERENCES, isDefaultLookPreference, type DefaultLookPreference } from '../data/defaultLook';
import { listProfileSummaries, resolveStylesFolder } from './stylesProfiles';
import { ProfileEditorModal } from './ProfileEditorModal';
import { saveSecret, type SecretStore } from './publishSecrets';

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
  tlsCheck: boolean;
  taskList: boolean;
  /** One time limit for the network phases of a capture, in minutes. Set to 0 for no limit. */
  captureDeadlineMinutes: number;
  defaultViewMode: GlobeViewMode;
  themeBehavior: 'obsidian' | 'dark' | 'light';
  openInSplitPane: boolean;
  syncActiveNote: boolean;
  /** Where Publish audit writes the client report JSON (a full folder path). Empty: Publish audit is off. */
  clientReportsFolder: string;
  /** What a link starts with, ending where the file name goes, for example http://127.0.0.1:4177/report.html?report=/reports/ */
  clientReportLinkBase: string;
  /** Publish with push: where Publish audit sends the report (https ingest address, host:/folder for ssh, or a full local folder). Empty: save to the client reports folder. */
  publishTarget: string;
  /** For ssh and folder targets: the public address of the report viewer, so the link can be shown (the https route returns its own link). */
  publishLinkBase: string;
  /** Explicit opt-in: also read WEBOBS_INGEST_SECRET, CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET from the environment. Off by default. */
  publishEnvSecrets: boolean;
  /** Pre-filled in the approval box when publishing. */
  clientApproverName: string;
  /** Where the client's feedback is addressed in the report file. Empty: none. */
  clientFeedbackEmail: string;
  /** The folder with the style profiles for Publish (agency.json, clients/<name>.json, optional default.json). A full path, or relative to the vault. Empty: .web-obs/styles in the vault. */
  stylesFolder: string;
  /** The look chosen last time in the Publish dialog: default, agency or client:<file>. */
  stylesChoice: string;
  /** Which look the Publish dialog starts on: auto (client profile for the site, else the Agency profile, else Default), agency, default or last. */
  defaultLook: DefaultLookPreference;
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
  tlsCheck: true,
  taskList: true,
  captureDeadlineMinutes: 0,
  defaultViewMode: 'globe',
  themeBehavior: 'obsidian',
  openInSplitPane: true,
  syncActiveNote: true,
  clientReportsFolder: '',
  clientReportLinkBase: '',
  publishTarget: '',
  publishLinkBase: '',
  publishEnvSecrets: false,
  clientApproverName: '',
  clientFeedbackEmail: '',
  stylesFolder: '',
  stylesChoice: 'default',
  defaultLook: 'auto',
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

  /** The "Style profiles" list: Agency and each client profile with a one-line summary and any problem, with Edit. There is no delete in this version. */
  private renderStyleProfiles(containerEl: HTMLElement): void {
    new Setting(containerEl).setName('Style profiles').setHeading();
    const adapter = this.app.vault.adapter;
    const vaultBase = adapter instanceof FileSystemAdapter ? adapter.getBasePath() : '.';
    const folder = resolveStylesFolder(vaultBase, this.bridge.settings.stylesFolder);
    const list = listProfileSummaries(folder);
    const intro = containerEl.createEl('p', { cls: 'setting-item-description', text: list.length ? 'Edit changes the profile file in place and keeps the previous version as a .bak copy next to it. There is no delete in this version: to remove a profile, delete its file in the styles folder.' : 'No style profiles yet. Create one from the Look list when you press Publish on an audit.' });
    void intro;
    for (const p of list) {
      new Setting(containerEl)
        .setName((p.kind === 'agency' ? 'Agency: ' : 'Client: ') + p.label)
        .setDesc(p.problem ? 'Needs a fix: ' + p.problem : p.summary)
        .addButton((b) => b.setButtonText('Edit').onClick(() => new ProfileEditorModal(this.app, { folder, id: p.id, onDone: () => { containerEl.empty(); this.renderSettings(containerEl); } }).open()));
    }
  }

  // Modern Obsidian can discover the tab through settings search. Older hosts use display().
  override getSettingDefinitions(): SettingDefinitionItem[] {
    return [{
      name: 'Web-Obs capture, map and client reports',
      desc: 'Python engine, page limits, images, browser audits, screenshots, spelling, DNS, TLS, tasks, layouts, theme, publish destinations, approval and secrets.',
      aliases: ['website', 'sitemap', 'archive', 'feedback', 'Cloudflare'],
      render: (setting) => {
        setting.settingEl.empty();
        setting.settingEl.removeClass('setting-item');
        this.renderSettings(setting.settingEl);
      },
    }];
  }

  override display(): void {
    this.containerEl.empty();
    this.renderSettings(this.containerEl);
  }

  private renderSettings(containerEl: HTMLElement): void {
    ;

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
        btn.setButtonText('Check engine').onClick(async () => {
          const adapter = this.app.vault.adapter;
          const vaultBase = adapter instanceof FileSystemAdapter ? adapter.getBasePath() : '.';
          const scriptPath = path.join(
            vaultBase,
            this.pluginRef.manifest.dir ?? `${this.app.vault.configDir}/plugins/web-obs`,
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
        .addOption('preferred', 'Preferred images (recommended)')
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
          .addOption('auto', 'Auto (recommended)')
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
      .setDesc('Opens up to five pages in the headless browser after capture for lab timings, automated accessibility rules (axe-core), screenshots, JavaScript dependence and third parties on first load. Needs Playwright and Chromium; skipped with fast HTTP only.')
      .addToggle((toggle) =>
        toggle.setValue(this.bridge.settings.browserAudit ?? true).onChange(async (value) => {
          this.bridge.settings.browserAudit = value;
          await this.bridge.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName('Page snapshots')
      .setDesc('Saves a full-page screenshot of the most important pages after capture and shows it at the top of each note. Needs Playwright and Chromium; skipped with fast HTTP only.')
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
      .setName('Certificate check')
      .setDesc('Reads the TLS certificate over one handshake with the site: who issued it, when it expires and which names it covers.')
      .addToggle((toggle) =>
        toggle.setValue(this.bridge.settings.tlsCheck ?? true).onChange(async (value) => {
          this.bridge.settings.tlsCheck = value;
          await this.bridge.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName('Task list')
      .setDesc('Writes _tasks.md, a checklist of fixes from the audit that keeps your ticks between captures. Turn it off if you track tasks somewhere else.')
      .addToggle((toggle) =>
        toggle.setValue(this.bridge.settings.taskList ?? true).onChange(async (value) => {
          this.bridge.settings.taskList = value;
          await this.bridge.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName('Capture time limit')
      .setDesc('Minutes a capture may spend on the network, across every phase. When it runs out, the capture stops requesting, saves what it has and is marked partial. Set to 0 for no limit.')
      .addText((text) =>
        text.setPlaceholder('0').setValue(String(this.bridge.settings.captureDeadlineMinutes ?? 0)).onChange(async (value) => {
          const minutes = Number(value.trim() || '0');
          if (!Number.isFinite(minutes) || minutes < 0 || minutes > 1440) return;
          this.bridge.settings.captureDeadlineMinutes = minutes;
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
          .addOption('globe', 'Site Globe (3D sphere)')
          .addOption('road', 'Sitemap Road (click depth)')
          .addOption('clusters', 'Link Clusters (force)')
          .setValue(this.bridge.settings.defaultViewMode)
          .onChange(async (value) => {
            this.bridge.settings.defaultViewMode = value as GlobeViewMode;
            await this.bridge.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName('Theme')
      .setDesc('Follow Obsidian theme or force dark / light.')
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

    new Setting(containerEl).setName('Client reports').setHeading();
    const text = (name: string, desc: string, key: 'clientReportsFolder' | 'clientReportLinkBase' | 'clientApproverName' | 'clientFeedbackEmail' | 'publishTarget' | 'publishLinkBase' | 'stylesFolder', placeholder: string) =>
      new Setting(containerEl).setName(name).setDesc(desc).addText((t) => t
        .setPlaceholder(placeholder)
        .setValue(this.bridge.settings[key])
        .onChange(async (value) => {
          this.bridge.settings[key] = value.trim();
          await this.bridge.saveSettings();
        }));
    text('Client reports folder', 'Publish audit in the audit view saves the client report here, as one file with a random name. Use a full folder path.', 'clientReportsFolder', 'C:\\path\\to\\reports');
    text('Report link base', 'The start of the link shown after publishing, ending where the file name goes. Leave empty to skip the link.', 'clientReportLinkBase', 'http://127.0.0.1:4177/report.html?report=/reports/');
    text('Publish target', 'Optional. Where Publish audit sends the report instead of saving it. Give the report front end address only, for example audit.example.com (https is required; the upload route is added for you). Also accepted: host:/folder over ssh (a name from your ssh config), or a full local folder.', 'publishTarget', 'audit.example.com');
    const secretStore = (this.app as unknown as { secretStorage?: SecretStore }).secretStorage;
    const secretField = (name: string, desc: string, id: SecretName) => new Setting(containerEl).setName(name).setDesc(desc).addText((t) => {
      t.inputEl.type = 'password'; t.inputEl.autocomplete = 'off';
      t.setPlaceholder(secretStore ? (secretStore.getSecret(id) ? 'Saved (hidden). Type to replace.' : 'Not set') : 'Not available in this Obsidian');
      t.inputEl.disabled = !secretStore;
      // The value goes straight into Obsidian's secret storage. It is never put in this.bridge.settings, so it never reaches data.json.
      // Saved when the field is left or Enter is pressed (the "change" event), never on every keystroke, so a half-typed secret is never stored.
      t.inputEl.addEventListener('change', () => { const v = t.inputEl.value.trim(); if (v && saveSecret(secretStore, id, v)) { t.inputEl.value = ''; t.setPlaceholder('Saved (hidden). Type to replace.'); } });
    });
    secretField('Publish secret', 'The ingest secret for the publish target. It is stored by Obsidian; the secret never goes into data.json or the vault. If you leave this empty, Publish asks for it once per session and keeps it in memory only.', SECRET_NAMES.ingest);
    secretField('Cloudflare Access ID', 'Optional. The Cloudflare Access service token ID, stored the same way.', SECRET_NAMES.cfId);
    secretField('Cloudflare Access secret', 'Optional. The Cloudflare Access service token secret, stored the same way.', SECRET_NAMES.cfSecret);
    new Setting(containerEl).setName('Also read secrets from environment variables').setDesc('Off by default. When on, WEBOBS_INGEST_SECRET, CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET are used if no stored secret exists. They must be present where Obsidian was started.')
      .addToggle((tg) => tg.setValue(this.bridge.settings.publishEnvSecrets).onChange(async (v) => { this.bridge.settings.publishEnvSecrets = v; await this.bridge.saveSettings(); }));
    text('Report viewer address', 'For ssh and folder targets: the public address of the report viewer, for example https://audit.example.com, so the link can be shown. Not needed for https.', 'publishLinkBase', 'https://audit.example.com');
    text('Approved by', 'Your name, pre-filled when you publish. A person approves what goes to a client.', 'clientApproverName', 'Your name');
    text('Style profiles folder', 'Optional. The folder with the looks Publish can send with a report: agency.json, a clients folder with one file per client, and an optional default.json. A full path, or a path inside the vault. Empty: .web-obs/styles in the vault. Everything in these files is visible to anyone who has the report link.', 'stylesFolder', '.web-obs/styles');
    new Setting(containerEl).setName('Default look when publishing').setDesc('Which look the dialog starts on. You can change it for each report. The recommended choice uses the client profile named after the site, then the agency profile, then the default look.').addDropdown((d) => {
      for (const p of DEFAULT_LOOK_PREFERENCES) d.addOption(p.id, p.label);
      d.setValue(isDefaultLookPreference(this.bridge.settings.defaultLook) ? this.bridge.settings.defaultLook : 'auto').onChange(async (v) => { this.bridge.settings.defaultLook = isDefaultLookPreference(v) ? v : 'auto'; await this.bridge.saveSettings(); });
    });
    this.renderStyleProfiles(containerEl);
    text('Client feedback address', 'Where the client report says feedback is sent. Optional.', 'clientFeedbackEmail', 'you@your-agency.example');
  }
}
