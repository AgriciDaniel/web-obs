"""Record local engine identity and requested settings without network access."""
import hashlib
from importlib import metadata
from pathlib import Path
import platform
import sys


def capture_provenance(configuration):
    root = Path(__file__).resolve().parent
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.iterdir())
             if p.is_file() and (p.suffix == '.py' or p.name == 'requirements.txt')}
    versions = {}
    for name in ('requests', 'beautifulsoup4', 'lxml', 'trafilatura', 'htmldate', 'playwright',
                 'dnspython', 'pyspellchecker', 'html5lib'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    identity = '\n'.join(f'{name}:{digest}' for name, digest in files.items())
    return {'schemaVersion': 1, 'configuration': dict(configuration),
            'engineSha256': hashlib.sha256(identity.encode()).hexdigest(),
            'engineFiles': files,
            'runtime': {'pythonVersion': platform.python_version(),
                        'pythonExecutable': sys.executable,
                        'platform': sys.platform, 'packages': versions},
            'browserEvidence': 'Per-page renderUsed and rawKind record whether rendering occurred; browser runtime acceptance is separate.'}


def assert_engine_unchanged(provenance):
    if capture_provenance({})['engineSha256'] != provenance['engineSha256']:
        raise RuntimeError('Engine source changed during collection. Previous capture preserved; retry with a stable engine.')
