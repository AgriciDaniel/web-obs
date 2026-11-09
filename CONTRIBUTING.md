# Contributing

Thanks for helping. Bug reports and small, focused pull requests are the most useful.

## Reporting a bug

Run **Web-Obs: Run diagnostics** in Obsidian, press **Copy report**, and paste it into your issue along with the website you were capturing and what you expected to happen.

## Working on the code

```bash
npm ci
python3.14 -m venv engine/.venv
engine/.venv/bin/pip install -r engine/requirements.txt
npm run verify
```

`npm run lint` runs the pinned official Obsidian recommended source rules. It requires zero errors and warnings, with browser/Node scopes and product terminology documented in `eslint.config.mjs`. Use Node.js 22.13 or newer for the development toolchain. The lockfile overrides affected lint-tool minimatch releases with 11.0.1 and pins moment to 2.31.0 for the official lint plugin. These overrides do not enter the plugin bundle.

`npm run verify` includes lint and is the one check that must pass before a pull request. It builds the plugin, runs the crawler against local test sites and runs every test.

A few house rules:

- Keep Web-Obs local. No AI services, analytics or API keys.
- Add a test for any behavior you change.
- Do not use em or en dashes in code, docs or messages. The verify step checks this.
- Do not add automatic installs of Python packages or browsers.

See the [technical reference](docs/TECHNICAL.md) for how the pieces fit.
