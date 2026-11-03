"""Find an existing Playwright Chromium without changing the environment."""
import os
from pathlib import Path
import sys


def _executable(path: Path) -> bool:
    return path.is_file() and (os.name == 'nt' or os.access(path, os.X_OK))


def resolve_chromium_executable(driver) -> dict:
    """Use Playwright's exact expected revision, then standard user caches.

    Flatpak gives Obsidian its own XDG cache while a manually prepared Python
    environment can use the host user's browser cache. Pass the resolved binary
    explicitly to launch so readiness and execution cannot choose different files.
    An explicit PLAYWRIGHT_BROWSERS_PATH remains authoritative, including '0'.
    """
    expected = Path(driver.chromium.executable_path)
    result = {'executablePath': None, 'expectedPath': str(expected), 'source': None, 'error': None}
    if _executable(expected):
        return {**result, 'executablePath': str(expected), 'source': 'playwright-default'}
    if os.environ.get('PLAYWRIGHT_BROWSERS_PATH'):
        return {**result, 'error': f'The configured PLAYWRIGHT_BROWSERS_PATH has no compatible executable at {expected}.'}
    installation = next((parent for parent in expected.parents if parent.name.startswith('chromium-')), None)
    if installation is not None:
        relative = expected.relative_to(installation.parent)
        if sys.platform == 'darwin':
            caches = [Path.home() / 'Library' / 'Caches' / 'ms-playwright']
        elif os.name == 'nt':
            caches = [Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'ms-playwright']
        else:
            caches = [Path.home() / '.cache' / 'ms-playwright']
        for cache in caches:
            candidate = cache / relative
            if _executable(candidate):
                return {**result, 'executablePath': str(candidate), 'source': 'standard-user-cache'}
    return {**result, 'error': f'Compatible Chromium was not found at {expected} or the standard user browser cache. Nothing was installed.'}
