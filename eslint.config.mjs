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
  // The standalone browser app has no Obsidian, so this file supplies createEl for it with the DOM API.
  files: ['src/standaloneDom.ts'],
  rules: { 'obsidianmd/prefer-create-el': 'off' },
});
