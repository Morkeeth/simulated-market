"""Frozen builder-owned source on real Nebius filesystem branches."""
import hashlib
import io
import shlex
import tarfile
from pathlib import Path, PurePosixPath
from sim.adapters.nebius import NebiusSandbox, ENV, preparation_command, Fork


# Dependencies must be selected by reviewed setup, never the pinned demo wheelhouse.
SCENARIO_ENV = {**ENV, 'PIP_FIND_LINKS': ''}


class NebiusScenarioSandbox(NebiusSandbox):
    def __init__(self, contract, output, *, record, sdk=None):
        super().__init__(sdk=sdk, base_image=contract['image_id'], record=record)
        self.contract, self.output = contract, Path(output)
        self._scenario_checkpoint = None

    def checkpoint_target(self, target):
        c = self.contract
        recipe = {'scenario_sha256': target.meta['scenario']['sha256'],
                  'source_sha256': c['source']['sha256'], 'base_id': c['image_id'],
                  'workdir': '/work', 'network': 'provider-default; not claimed isolated'}
        if self._scenario_checkpoint:
            checkpoint, saved = self._scenario_checkpoint
            if any(saved[k] != v for k, v in recipe.items()):
                raise ValueError('Scenario changed after checkpoint freeze.')
            return checkpoint, dict(saved)
        raw = (self.output / 'source.tar').read_bytes()
        if hashlib.sha256(raw).hexdigest() != c['source']['sha256']:
            raise ValueError('Frozen source archive changed.')
        files, modes = {}, {}
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if (not member.isfile() or path.is_absolute() or '..' in path.parts
                        or member.name in files or member.name not in c['source']['files']):
                    raise ValueError('Source archive contains unsupported members.')
                data = archive.extractfile(member).read()
                if hashlib.sha256(data).hexdigest() != c['source']['files'][member.name]:
                    raise ValueError('Source archive file changed.')
                files[member.name] = data
                modes[member.name] = member.mode & 0o777
        if set(files) != set(c['source']['files']):
            raise ValueError('Source archive allowlist differs.')
        image = self.preflight().run(shell=preparation_command(), env=SCENARIO_ENV, timeout=60,
                    disposable=False, stdout=str, stderr=str).wait()
        if image.exit_code != 0 or image.uuid is None:
            raise RuntimeError('Use a clean Python image with empty /work, venv, pip and bash support.')
        permissions = ' && '.join(f'chmod {mode:o} '+shlex.quote('/work/'+name) for name, mode in sorted(modes.items()))
        image = image.run(shell=permissions, cwd='/work', files={'/work/'+k:v for k,v in files.items()},
                          env=SCENARIO_ENV, timeout=60, disposable=False, stdout=str, stderr=str).wait()
        if image.exit_code != 0 or image.uuid is None:
            raise RuntimeError('Frozen source upload failed.')
        fork = Fork(image, self.record, env=SCENARIO_ENV)
        for command in c['setup']:
            code, _ = fork.exec(['bash', '-c', command])
            if code:
                raise RuntimeError('Frozen scenario setup failed; no population was run.')
        checkpoint = str(fork.image.uuid)
        fork.close()
        recipe['checkpoint_image_id'] = checkpoint
        self._scenario_checkpoint = checkpoint, recipe
        self.record({'service': self.name, 'operation': 'scenario-checkpoint', 'image_id': checkpoint,
                     'source_sha256': recipe['source_sha256']})
        return checkpoint, dict(recipe)

    def fork(self, checkpoint_id, name):
        if not self._scenario_checkpoint or checkpoint_id != self._scenario_checkpoint[0]:
            raise ValueError('Fork must use the frozen scenario checkpoint.')
        return Fork(self.sdk.images.use(checkpoint_id), self.record, env=SCENARIO_ENV)
