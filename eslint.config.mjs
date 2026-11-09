import tseslint from 'typescript-eslint';
import obsidianmd from 'eslint-plugin-obsidianmd';

export default tseslint.config(...obsidianmd.configs.recommended, {
  files: ['**/*.ts', '**/*.tsx'],
  rules: {
    'obsidianmd/ui/sentence-case': ['warn', {
      brands: ['Web-Obs', 'Site Globe', 'Sitemap Road', 'Link Clusters', 'Python', 'Playwright', 'Chromium', 'Markdown', 'JavaScript', 'English', 'dnspython', 'pyspellchecker', 'Obsidian', 'WEBOBS_INGEST_SECRET', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET'],
      acronyms: ['HTTPS', 'HTTP', 'SPA', '3D', 'MX', 'SPF', 'DMARC', 'DKIM', 'CAA', 'DNS', 'URL', 'HTML', 'TLS', 'UI', 'WEBOBS_INGEST_SECRET', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET'],
    }],
  },
  languageOptions: {
    parserOptions: { project: './tsconfig.json', tsconfigRootDir: import.meta.dirname },
  },
}, {
  // This renderer also runs in ordinary browsers without Obsidian DOM helpers.
  files: ['src/components/SiteGlobeCanvas3D.tsx', 'src/components/brandBadge.ts'],
  rules: { 'obsidianmd/prefer-create-el': 'off' },
}, {
  // The standalone adapter uses same-origin, abortable, streaming fetch in a browser.
  files: ['src/obsidian/hostAdapter.ts'],
  rules: { 'no-restricted-globals': ['warn', 'app', 'localStorage', 'warn'] },
}, {
  // Layout scheduling is shared with Node verification and the standalone browser.
  files: ['src/data/globeLayout.ts'],
  rules: { 'obsidianmd/prefer-window-timers': 'off' },
}, {
  // Developer overrides must also be readable by Node fixture tools.
  files: ['src/components/nodeLook.ts'],
  rules: { 'obsidianmd/no-global-this': 'off' },
});
