import { FileSystemAdapter, Modal, Notice, Plugin, Setting, type WorkspaceLeaf } from 'obsidian';
import { WEB_OBS_VIEW_TYPE } from '../obsidian/hostAdapter';
import type { GlobeViewMode } from '../types/site';
import {
  DEFAULT_WEB_OBS_SETTINGS,
  type WebObsPluginSettings,
  WebObsSettingTab,
} from './settings';
import { SiteGlobeView } from './SiteGlobeView';
import { DoctorModal } from './DoctorModal';
import { runDoctor } from './doctor';
import { installEngine } from './engineBundle';
import path from 'node:path';

class QuickCaptureModal extends Modal {
  private onSubmitUrl: (url: string) => void;
  private value = '';

  constructor(plugin: Plugin, onSubmitUrl: (url: string) => void) {
    super(plugin.app);
    this.onSubmitUrl = onSubmitUrl;
  }

  override onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl('h3', { text: 'Capture Website' });

    new Setting(contentEl)
      .setName('Website domain or URL')
      .setDesc('Sitemap first, then page content and local images, then internal and external links.')
      .addText((text) => {
        text.setPlaceholder('websiteexample.com').onChange((val) => {
          this.value = val;
        });
        text.inputEl.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter' && this.value.trim()) {
            ev.preventDefault();
            const target = this.value.trim();
            this.close();
            this.onSubmitUrl(target);
          }
        });
        window.setTimeout(() => text.inputEl.focus(), 20);
      })
      .addButton((btn) =>
        btn
          .setButtonText('Start')
          .setCta()
          .onClick(() => {
            if (!this.value.trim()) return;
            const target = this.value.trim();
            this.close();
            this.onSubmitUrl(target);
          })
      );
  }

  override onClose(): void {
    this.contentEl.empty();
  }
}

export default class WebObsPlugin extends Plugin {
  settings: WebObsPluginSettings = { ...DEFAULT_WEB_OBS_SETTINGS };

  override async onload(): Promise<void> {
    await this.loadSettings();
    this.unpackEngine();

    this.registerView(
      WEB_OBS_VIEW_TYPE,
      (leaf: WorkspaceLeaf) => new SiteGlobeView(leaf, this)
    );

    this.addRibbonIcon('globe', 'Open Web-Obs Site Globe', () => {
      void this.activateView();
    });

    this.addCommand({
      id: 'open-site-globe',
      name: 'Open 3D Site Globe',
      callback: () => {
        void this.activateView('globe');
      },
    });

    this.addCommand({
      id: 'capture-website',
      name: 'Capture Website into Vault',
      callback: () => {
        new QuickCaptureModal(this, async (url) => {
          const view = await this.activateView('globe');
          await view?.runCrawlFromPlugin({ url });
        }).open();
      },
    });

    this.addCommand({
      id: 'run-diagnostics',
      name: 'Run diagnostics',
      callback: () => this.openDiagnostics(),
    });

    this.addCommand({
      id: 'open-sitemap-road',
      name: 'Open in Sitemap Road mode',
      callback: () => {
        void this.activateView('road');
      },
    });

    this.addCommand({
      id: 'focus-active-note-in-globe',
      name: 'Focus active note on 3D Site Globe',
      callback: async () => {
        const activeFile = this.app.workspace.getActiveFile();
        const view = await this.activateView();
        if (!activeFile) {
          new Notice('No active Markdown note to focus.');
          return;
        }
        if (view && !view.focusNoteInGlobe(activeFile, true)) {
          new Notice(`"${activeFile.name}" is not part of the active website graph.`);
        }
      },
    });

    this.addSettingTab(
      new WebObsSettingTab(this.app, this, {
        settings: this.settings,
        saveSettings: () => this.saveSettings(),
        notifySettingsChanged: () => this.notifyViewsOfSettings(),
      })
    );

    this.app.workspace.onLayoutReady(() => {
      if (this.app.workspace.getLeavesOfType(WEB_OBS_VIEW_TYPE).length > 0) {
        return;
      }
      const emptyLeaves = this.app.workspace.getLeavesOfType('empty');
      if (emptyLeaves.length > 0) {
        void emptyLeaves[0].setViewState({
          type: WEB_OBS_VIEW_TYPE,
          active: true,
          state: { viewMode: this.settings.defaultViewMode },
        });
      }
    });
  }

  /** Obsidian only installs main.js, manifest.json and styles.css, so unpack the packed engine beside them. */
  private unpackEngine(): void {
    const adapter = this.app.vault.adapter;
    if (!(adapter instanceof FileSystemAdapter)) return;
    try {
      const pluginAbs = path.join(adapter.getBasePath(), this.manifest.dir ?? '.obsidian/plugins/web-obs');
      const result = installEngine(pluginAbs);
      if (result.state === 'installed') new Notice('Web-Obs: capture engine installed. Run diagnostics to check your Python setup.');
    } catch (error) {
      new Notice(`Web-Obs could not unpack its capture engine: ${error instanceof Error ? error.message : String(error)}`, 10000);
    }
  }

  openDiagnostics(): void {
    new DoctorModal(this.app, () => {
      const adapter = this.app.vault.adapter;
      return runDoctor({
        vaultBase: adapter instanceof FileSystemAdapter ? adapter.getBasePath() : null,
        pluginDir: this.manifest.dir ?? '.obsidian/plugins/web-obs',
        pluginVersion: this.manifest.version,
        pythonBinary: this.settings.pythonBinary || 'python3.14',
        renderMode: this.settings.renderMode,
      });
    }).open();
  }

  async loadSettings(): Promise<void> {
    const loaded = (await this.loadData()) as Partial<WebObsPluginSettings> | null;
    this.settings = Object.assign({}, DEFAULT_WEB_OBS_SETTINGS, loaded ?? {});
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  private notifyViewsOfSettings(): void {
    for (const leaf of this.app.workspace.getLeavesOfType(WEB_OBS_VIEW_TYPE)) {
      if (leaf.view instanceof SiteGlobeView) {
        leaf.view.emitTheme();
      }
    }
  }

  async activateView(modeOverride?: GlobeViewMode): Promise<SiteGlobeView | null> {
    const { workspace } = this.app;
    const existing = workspace.getLeavesOfType(WEB_OBS_VIEW_TYPE);
    let leaf: WorkspaceLeaf;

    if (existing.length > 0) {
      leaf = existing[0];
    } else {
      leaf = workspace.getLeaf('tab');
      await leaf.setViewState({
        type: WEB_OBS_VIEW_TYPE,
        active: true,
        state: {
          viewMode: modeOverride ?? this.settings.defaultViewMode,
        },
      });
    }

    await workspace.revealLeaf(leaf);

    if (leaf.view instanceof SiteGlobeView) {
      if (modeOverride) {
        leaf.view.dispatchCommand({ type: 'set-view-mode', viewMode: modeOverride });
      }
      return leaf.view;
    }
    return null;
  }
}
