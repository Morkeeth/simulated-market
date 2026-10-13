"""Nebius Sandboxes via the pinned contree-sdk 0.3.6 API.

See docs/real-backends.md for the published SDK / current docs constructor
mismatch. No image import, no silent local fallback, and no implicit key lookup
outside the documented environment and key file.
"""
from __future__ import annotations

import hashlib
import os
import shlex
from pathlib import Path
from uuid import UUID

from sim.errors import NoKey, NotWired
from sim.labels import RUNTIME

KEY_ENV = 'NEBIUS_API_KEY'
KEY_PATH = Path.home() / '.config' / 'keys' / 'nebius.key'
BASE_URL = 'https://api.tokenfactory.nebius.com/sandboxes'
IMAGE_ENV = 'NEBIUS_SANDBOX_IMAGE'
ENV = {'PIP_NO_INDEX': '1', 'PIP_FIND_LINKS': '/sim-market-wheels',
       'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PIP_ROOT_USER_ACTION': 'ignore',
       'PIP_PROGRESS_BAR': 'off', 'PIP_CONFIG_FILE': '/dev/null', 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
       'PATH': '/sim-market-venv/bin:/usr/local/bin:/usr/bin:/bin',
       'PYTHONPATH': '', 'PYTHONHOME': '', 'BASH_ENV': '', 'ENV': ''}


def preparation_command(workdir='/work', venv='/sim-market-venv', *,
                        wheel_name=None, wheel_sha=None, wheel_dir='/sim-market-wheels'):
    work, environment = shlex.quote(workdir), shlex.quote(venv)
    # Never clear an inherited directory or silently accept a completed target.
    # venv excludes preinstalled system packages; all participant commands use it.
    wheel_check = ''
    if wheel_name is not None:
        code = ("from pathlib import Path; import hashlib; "
                f"p=Path({wheel_dir!r}); f=p/{wheel_name!r}; "
                "assert p.is_dir() and not p.is_symlink(); "
                f"assert sorted(x.name for x in p.iterdir()) == [{wheel_name!r}]; "
                "assert f.is_file() and not f.is_symlink(); "
                f"assert hashlib.sha256(f.read_bytes()).hexdigest() == {wheel_sha!r}")
        wheel_check = 'python -c ' + shlex.quote(code) + '; '
    return (f'set -eu; test ! -e {environment}; '
            f'if test -d {work}; then test -z "$(ls -A {work})"; fi; '
            f'{wheel_check}mkdir -p {work}; command -v bash >/dev/null; command -v sh >/dev/null; '
            f'python -m venv {environment}; {environment}/bin/python -m pip --version; '
            f'{environment}/bin/python -c "import importlib.util; '
            'assert importlib.util.find_spec(\'dotenv\') is None"')


def load_key():
    key = os.environ.get(KEY_ENV, '').strip()
    if not key and KEY_PATH.is_file():
        key = KEY_PATH.read_text().strip()
    if not key:
        raise NoKey(f'Set {KEY_ENV} or provide {KEY_PATH}; Sandboxes access is required.')
    return key


def configured_image():
    value = os.environ.get(IMAGE_ENV, '').strip()
    try:
        return str(UUID(value))
    except ValueError:
        raise NoKey(f'Set {IMAGE_ENV} to an existing Python sandbox image UUID, not a mutable tag.') from None


def make_sdk():
    key = load_key()
    from importlib.metadata import version, PackageNotFoundError
    try:
        if version('contree-sdk') != '0.3.6':
            raise NotWired('Install requirements-sponsor.txt: this adapter requires contree-sdk 0.3.6.')
        from contree_sdk import ContreeSync
    except (ImportError, PackageNotFoundError):
        raise NotWired('Install requirements-sponsor.txt in your Python environment.') from None
    return ContreeSync(token=key, base_url=BASE_URL)


class Fork:
    def __init__(self, image, record, *, env=None):
        self.image, self.record, self.closed = image, record, False
        self.env = dict(ENV if env is None else env)

    def exec(self, argv, stdin=None):
        if self.closed:
            raise RuntimeError('Nebius fork is closed')
        child = self.image.run(command=argv[0], args=argv[1:], stdin=stdin,
                               cwd='/work', env=self.env, timeout=60, disposable=False,
                               stdout=str, stderr=str, truncate_output_at=65536).wait()
        if not isinstance(child.exit_code, int) or child.uuid is None:
            raise RuntimeError('Nebius returned no completed command state')
        # Nonzero commands can still change files. Preserve that state for retries.
        self.image = child
        self.record({'service': 'nebius-sandboxes', 'operation': 'command',
                     'image_id': str(child.uuid), 'exit_code': child.exit_code})
        return child.exit_code, (child.stdout or '') + (child.stderr or '')

    def close(self):
        # Commands are finite executions, not live daemons. This does not delete
        # retained remote snapshots; no documented delete API is assumed.
        self.closed = True


class NebiusSandbox:
    name, label = 'nebius-sandboxes', RUNTIME

    def __init__(self, *, sdk=None, base_image=None, record=None):
        self.sdk = sdk if sdk is not None else make_sdk()
        self.base_image = base_image or configured_image()
        self.record = record or (lambda row: None)
        self._checkpoint = None

    def preflight(self):
        # Metadata lookup only. Does not import an image or execute a command.
        return self.sdk.images.use(self.base_image, strict=True)

    def checkpoint(self, wheel_path, wheel_sha256):
        wheel = Path(wheel_path)
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != wheel_sha256:
            raise ValueError('wheel sha256 mismatch')
        key = (wheel.name, wheel_sha256)
        if self._checkpoint is not None:
            old_key, checkpoint, recipe = self._checkpoint
            if old_key != key:
                raise ValueError('checkpoint is already frozen for a different wheel')
            return checkpoint, recipe
        image = self.preflight()
        child = image.run(shell=preparation_command(wheel_name=wheel.name, wheel_sha=wheel_sha256),
                          files={f'/sim-market-wheels/{wheel.name}': wheel}, env=ENV,
                          timeout=60, disposable=False, stdout=str, stderr=str).wait()
        if child.exit_code != 0 or child.uuid is None:
            raise RuntimeError('Nebius checkpoint preparation failed; existing image must contain Python')
        checkpoint = str(child.uuid)
        recipe = {'base_image': self.base_image, 'checkpoint_image_id': checkpoint,
                  'wheel': wheel.name, 'wheel_sha256': wheel_sha256,
                  'env': ENV, 'workdir': '/work'}
        self._checkpoint = (key, checkpoint, recipe)
        self.record({'service': self.name, 'operation': 'checkpoint', 'image_id': checkpoint})
        return checkpoint, recipe

    def fork(self, checkpoint_id, name):
        return Fork(self.sdk.images.use(checkpoint_id), self.record)
