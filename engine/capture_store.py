"""Stage captures, preserve member files and recover interrupted promotions."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import signal
import tempfile
import uuid


def safe_parent(file, boundary):
    file, boundary = Path(file), Path(boundary)
    relative = file.relative_to(boundary)
    current = boundary
    for segment in relative.parts[:-1]:
        current = current / segment
        if current.is_symlink():
            raise ValueError(f'Capture parent is a symlink: {current}')
        current.mkdir(exist_ok=True)
    if file.is_symlink():
        raise ValueError(f'Capture file is a symlink: {file}')


def file_hash(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def files_under(root):
    root = Path(root)
    result = {}
    if not root.exists():
        return result
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            item = Path(directory) / name
            if item.is_symlink():
                raise ValueError(f'Capture paths must not contain a symlink: {item}')
        for name in files:
            item = Path(directory) / name
            if not item.is_file():
                raise ValueError(f'Unsupported capture file: {item}')
            result[item.relative_to(root).as_posix()] = item
    return result


def write_json(file, data):
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    if file.is_symlink():
        raise ValueError(f'Capture metadata is a symlink: {file}')
    descriptor, temporary_name = tempfile.mkstemp(prefix='.' + file.name + '-', dir=file.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, file)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def promotion_signals():
    # Keep the two directory renames indivisible with respect to ordinary cancellation.
    previous = None
    if hasattr(signal, 'pthread_sigmask'):
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
    try:
        yield
    finally:
        if previous is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)



def replace_directory(source, destination):
    """os.replace for folders. Windows can briefly deny renaming a folder that was just written."""
    delay = 0.05
    for attempt in range(8):
        try:
            return os.replace(source, destination)
        except PermissionError:
            if os.name != 'nt' or attempt == 7:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


class CaptureTransaction:
    def __init__(self, vault_dir):
        self.vault = Path(vault_dir).resolve()
        self.control = self.vault / '.web-obs'
        self.stage = None
        self.lock = None
        self.identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:10]

    def __enter__(self):
        if not self.vault.is_dir():
            raise ValueError('Vault directory does not exist.')
        for item in (self.control, self.vault / 'sites'):
            if item.is_symlink():
                raise ValueError(f'Capture destination is a symlink: {item}')
        self.control.mkdir(exist_ok=True)
        for name in ('staging', 'history', 'proposals'):
            directory = self.control / name
            if directory.is_symlink():
                raise ValueError(f'Capture destination is a symlink: {directory}')
            directory.mkdir(exist_ok=True)
        lock_path = self.control / 'capture.lock'
        if lock_path.is_symlink():
            raise ValueError('Capture lock is a symlink.')
        self.lock = lock_path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.lock.seek(0)
                if self.lock.read(1) == b'':
                    self.lock.write(b'0')
                    self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            self.lock = None
            raise RuntimeError('Another capture is running in this vault. Wait for it to finish or cancel it.') from exc
        try:
            self._recover()
            self.stage = Path(tempfile.mkdtemp(prefix=self.identifier + '-', dir=self.control / 'staging'))
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _recover(self):
        journal = self.control / 'promotion.json'
        if journal.is_symlink():
            raise ValueError('Capture journal is a symlink.')
        if not journal.exists():
            return
        data = json.loads(journal.read_text())
        site_id, history_id = data['siteId'], data['historyId']
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,179}', site_id) or not re.fullmatch(r'[a-zA-Z0-9-]+', history_id):
            raise ValueError('Invalid capture recovery journal.')
        active = self.vault / 'sites' / site_id
        history = self.control / 'history' / site_id / history_id
        safe_parent(history, self.control)
        if active.is_symlink() or history.is_symlink():
            raise ValueError('Capture recovery path is a symlink.')
        if not active.exists() and history.exists():
            active.parent.mkdir(exist_ok=True)
            replace_directory(history, active)
        journal.unlink()

    def commit(self, manifest, generated_paths=None):
        site_id = manifest.get('siteId', '')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,179}', site_id):
            raise ValueError('Invalid generated capture ID.')
        staged = self.stage / 'sites' / site_id
        active = self.vault / 'sites' / site_id
        if active.is_symlink():
            raise ValueError('Site destination is a symlink.')
        fresh = files_under(staged)
        if len(manifest['nodes']) > 20000 or len(manifest['edges']) > 200000:
            raise ValueError('Generated graph exceeds the supported 20,000-node / 200,000-edge inventory budget. Previous capture preserved.')
        node_ids = {n['id'] for n in manifest['nodes']}
        if len(node_ids) != len(manifest['nodes']) or any(e['source'] not in node_ids or e['target'] not in node_ids for e in manifest['edges']):
            raise ValueError('Generated graph references invalid nodes.')
        for node in manifest['nodes']:
            note = node['obsidianPath']
            prefix = f'sites/{site_id}/'
            if not note.startswith(prefix) or '..' in Path(note).parts or note[len(prefix):] not in fresh:
                raise ValueError(f'Generated note is missing or unsafe: {note}')
        if not fresh or '_site-graph.json' not in fresh:
            raise ValueError('Generated capture is incomplete.')
        previous = files_under(active)
        previous_hashes = {name: file_hash(file) for name, file in previous.items()}
        inventory = {}
        if '_generated-files.json' in previous:
            inventory = json.loads(previous['_generated-files.json'].read_text()).get('files', {})
        generated = {name: file_hash(file) for name, file in fresh.items()}
        preserved = []
        retained = []
        metadata = {'_site-graph.json', '_site-summary.json', '_generated-files.json', '_recapture-report.md'}
        for name, old_file in previous.items():
            if name in metadata:
                continue
            old_hash = previous_hashes[name]
            expected = inventory.get(name)
            if isinstance(expected, dict):
                expected = expected.get('generatedSha256')
            if name in fresh:
                if old_hash == generated[name] or (expected is not None and old_hash == expected):
                    continue
                # Legacy captures lack an edit baseline. Preserve their differing files too.
                proposal = self.control / 'proposals' / site_id / self.identifier / name
                safe_parent(proposal, self.control)
                shutil.copy2(fresh[name], proposal)
                shutil.copy2(old_file, fresh[name])
                preserved.append({'path': name, 'proposal': proposal.relative_to(self.vault).as_posix()})
            elif expected is None or old_hash != expected or (manifest.get('captureStatus') != 'complete' and name not in manifest.get('reclassifiedPagePaths', [])):
                destination = staged / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_file, destination)
                retained.append(name)
        if preserved:
            warning = f'Preserved {len(preserved)} locally edited or legacy files. Fresh generated versions are listed in _recapture-report.md.'
            manifest.setdefault('captureWarnings', []).append(warning)
            manifest['preservationStatus'] = 'conflicts'
            by_path = {row['path']: row['proposal'] for row in preserved}
            for node in manifest['nodes']:
                relative = node['obsidianPath'].removeprefix(f'sites/{site_id}/')
                if relative in by_path:
                    node['noteStatus'] = 'preserved-local-edits'
                    node['proposedNotePath'] = by_path[relative]
            reconciled_resources = False
            prefix = f'sites/{site_id}/'
            for resource in manifest.get('resources', []):
                local_path = resource.get('localPath')
                if not isinstance(local_path, str) or not local_path.startswith(prefix):
                    continue
                relative = local_path[len(prefix):]
                if relative not in by_path:
                    continue
                installed = staged / relative
                resource.update(sha256=file_hash(installed), bytes=installed.stat().st_size,
                                localFileStatus='preserved-local-edits',
                                proposedLocalPath=by_path[relative])
                reconciled_resources = True
            summary = json.loads((staged / '_site-summary.json').read_text())
            summary.update(preservationStatus='conflicts', captureWarnings=manifest['captureWarnings'])
            if reconciled_resources:
                summary['resources'] = manifest['resources']
                if '_resources.json' in fresh and '_resources.json' not in by_path:
                    resource_report = json.loads(fresh['_resources.json'].read_text())
                    resource_report['resources'] = manifest['resources']
                    write_json(fresh['_resources.json'], resource_report)
                    # This automatic metadata repair belongs to the generated
                    # baseline; it must not look like a member edit next time.
                    generated['_resources.json'] = file_hash(fresh['_resources.json'])
                    if generated_paths is not None:
                        generated_paths = set(generated_paths) | {'_resources.json'}
            write_json(staged / '_site-summary.json', summary)
        manifest['recapture'] = {'preservedFiles': preserved, 'retainedFiles': retained, 'historyId': self.identifier if previous else None}
        write_json(staged / '_site-graph.json', manifest)
        lines = ['# Recapture preservation', '', 'Previous captures are retained under `.web-obs/history/`.', 'Generated proposals are retained under `.web-obs/proposals/` for manual review.', '', '## Preserved files', '']
        lines += [f"- `{row['path']}`: proposal `{row['proposal']}`" for row in preserved] or ['None.']
        lines += ['', '## Retained files outside this generated inventory', '']
        lines += [f'- `{name}`' for name in retained] or ['None.']
        (staged / '_recapture-report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        inventory_out = {name: {'generatedSha256': digest, 'installedSha256': file_hash(staged / name)} for name, digest in generated.items() if name != '_generated-files.json'}
        if generated_paths is not None:
            # A metadata refresh must not adopt copied member files as generated.
            inventory_out = {name: row for name, row in inventory_out.items() if name in generated_paths}
            for name, row in inventory.items():
                if name not in generated_paths and name in fresh:
                    inventory_out[name] = row
        for name in ('_site-graph.json', '_site-summary.json', '_recapture-report.md'):
            inventory_out[name] = {'generatedSha256': file_hash(staged / name), 'installedSha256': file_hash(staged / name)}
        write_json(staged / '_generated-files.json', {'schemaVersion': 1, 'captureId': self.identifier, 'files': inventory_out})
        history_parent = self.control / 'history' / site_id
        if history_parent.is_symlink():
            raise ValueError('Capture history destination is a symlink.')
        history_parent.mkdir(exist_ok=True)
        history = history_parent / self.identifier
        active.parent.mkdir(exist_ok=True)
        journal = self.control / 'promotion.json'
        with promotion_signals():
            write_json(journal, {'siteId': site_id, 'historyId': self.identifier})
            if {name: file_hash(file) for name, file in files_under(active).items()} != previous_hashes:
                journal.unlink()
                raise RuntimeError('Vault files changed during publication. The previous capture was preserved; retry the capture.')
            if active.exists():
                replace_directory(active, history)
            try:
                if previous and {name: file_hash(file) for name, file in files_under(history).items()} != previous_hashes:
                    raise RuntimeError('Vault files changed during publication. The previous capture was preserved; retry the capture.')
                replace_directory(staged, active)
            except BaseException:
                if history.exists() and not active.exists():
                    replace_directory(history, active)
                raise
            journal.unlink()
        return manifest

    def __exit__(self, *_args):
        try:
            if self.stage and self.stage.exists():
                shutil.rmtree(self.stage, ignore_errors=os.name == 'nt')
        finally:
            if self.lock:
                self.lock.close()
                self.lock = None
