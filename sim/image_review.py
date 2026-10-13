"""Explicit custom-image review. Image code is never started during inspection."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import subprocess
from sim.standins.docker_sandbox import _docker

SUPPORTED_IMAGE = 'sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f'
MAX_REVIEW_PATHS = 500


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def metadata(image):
    result = json.loads(_docker('image', 'inspect', image).stdout)[0]
    return result['Id'], {k: result.get(k) for k in ('Architecture', 'Os', 'Config')}


def filesystem(image):
    # Read layers without creating a container: Docker-generated /dev and /etc
    # timestamps otherwise change on each export and obscure image differences.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(['docker', 'image', 'save', image], stdout=output,
                                stderr=subprocess.PIPE, timeout=300)
        if result.returncode: raise ValueError('Cannot read image layers for review.')
        output.seek(0)
        rows = {}
        with tarfile.open(fileobj=output, mode='r:*') as saved:
            manifest = json.load(saved.extractfile('manifest.json'))
            if len(manifest) != 1: raise ValueError('Expected one exact saved image.')
            for layer in manifest[0]['Layers']:
                with tarfile.open(fileobj=saved.extractfile(layer), mode='r|*') as archive:
                    additions, deletions, opaque = {}, [], []
                    for member in archive:
                        path = '/'+member.name.removeprefix('./').lstrip('/').rstrip('/')
                        if '..' in path.split('/'): raise ValueError('Unsafe image archive path.')
                        parent, _, leaf = path.rpartition('/')
                        if leaf == '.wh..wh..opq':
                            opaque.append(parent+'/'); continue
                        if leaf.startswith('.wh.'):
                            deletions.append(parent+'/'+leaf[4:]); continue
                        row = {'type': member.type.decode('ascii'), 'mode': member.mode,
                               'uid': member.uid, 'gid': member.gid, 'link': member.linkname,
                               'mtime': member.mtime, 'device': [member.devmajor, member.devminor],
                               'extended': member.pax_headers}
                        if member.isfile():
                            stream = archive.extractfile(member); sha = hashlib.sha256()
                            while chunk := stream.read(1024*1024): sha.update(chunk)
                            row.update(size=member.size, sha256=sha.hexdigest())
                        if member.islnk():
                            target = '/'+member.linkname.removeprefix('./').lstrip('/')
                            if '..' in target.split('/'):
                                raise ValueError('Unsafe image hardlink target.')
                            linked = additions.get(target, rows.get(target))
                            if linked is None or 'sha256' not in linked:
                                raise ValueError('Unsupported forward or non-file image hardlink.')
                            row.update(size=linked['size'], sha256=linked['sha256'])
                        additions[path] = row
                    # Whiteouts affect lower layers, never entries in their own layer.
                    rows = {p: row for p, row in rows.items()
                            if not any(p == d or p.startswith(d+'/') for d in deletions)
                            and not any(p.startswith(d) for d in opaque)}
                    for path, row in additions.items():
                        if row['type'] != '5':
                            rows = {p: value for p, value in rows.items() if not p.startswith(path+'/')}
                    rows.update(additions)
        return rows


def inspect(image):
    image_id, config = metadata(image)
    _, base_config = metadata(SUPPORTED_IMAGE)
    # Runtime volume initialization is outside this image-only contract.
    if config['Config'].get('Volumes') or base_config['Config'].get('Volumes'):
        raise ValueError('Declared image volumes are not supported by full-content review.')
    before, after = filesystem(SUPPORTED_IMAGE), filesystem(image_id)
    paths = {p: {'before': before.get(p), 'after': after.get(p)}
             for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)}
    config_diff = {k: {'before': base_config.get(k), 'after': config.get(k)}
                   for k in sorted(base_config.keys() | config.keys()) if base_config.get(k) != config.get(k)}
    # Config is deliberately complete: ENV, entrypoint, user, working dir,
    # command, healthcheck and labels must all be part of the review.
    old_env = {entry.partition('=')[0]: entry.partition('=')[2] for entry in base_config['Config'].get('Env', [])}
    new_env = {entry.partition('=')[0]: entry.partition('=')[2] for entry in config['Config'].get('Env', [])}
    environment_names = sorted(k for k in old_env.keys() | new_env.keys() if old_env.get(k) != new_env.get(k))
    runtime_fields = sorted(k for k in base_config['Config'].keys() | config['Config'].keys()
                            if base_config['Config'].get(k) != config['Config'].get(k))
    directories = Counter('/'.join(p.split('/')[:4]) for p in paths)
    packages = sorted({part for p in paths for part in p.split('/')
                       if part.endswith(('.dist-info', '.egg-info'))})
    payload = {'version': 1, 'base_image_id': SUPPORTED_IMAGE, 'image_id': image_id,
               'paths': paths, 'runtime_config': config_diff,
               'summary': {'changed_paths': len(paths), 'directories': dict(sorted(directories.items())),
                           'python_package_markers': packages, 'changed_environment_names': environment_names,
                           'runtime_config_fields': runtime_fields, 'review_path_limit': MAX_REVIEW_PATHS},
               'provider_exposure': 'The agent can read the full image filesystem and inherited environment. '
                   'Any of those bytes, selected source, docs and setup effects can reach the hosted model through command output. '
                   'Hashes identify content; they do not show that it contains no secrets.',
               'inspection_limit': 'Image layers are reconstructed with Docker whiteout semantics. '
                   'Docker-generated runtime mounts and files are outside the image content review. '
                   'No image code runs during inspection. File bytes, types, ownership, modes, links, device numbers, '
                   'timestamps and extended attributes are included as saved by Docker.'}
    return {'proposal': payload, 'proposal_digest': digest(payload), 'reviewed_digest': None}


def validate(review, image_id):
    if not isinstance(review, dict) or set(review) != {'proposal', 'proposal_digest', 'reviewed_digest'}:
        raise ValueError('Use an image-review manifest with an explicit reviewed digest.')
    proposal = review['proposal']
    if not isinstance(proposal, dict) or not isinstance(proposal.get('paths'), dict):
        raise ValueError('Image review proposal must include its exact path manifest.')
    actual = digest(proposal)
    if review['proposal_digest'] != actual or review['reviewed_digest'] != actual:
        raise ValueError('Image review is pending or changed. Review the exact proposal digest.')
    if proposal.get('image_id') != image_id or proposal.get('base_image_id') != SUPPORTED_IMAGE:
        raise ValueError('Image review does not match the frozen image and supported base.')
    if len(proposal.get('paths', {})) > MAX_REVIEW_PATHS:
        raise ValueError('Image diff exceeds the 500-path review limit. Use a smaller dependency image; no trust was granted.')
    observed = inspect(image_id)
    if observed['proposal_digest'] != actual:
        raise ValueError('Image content or runtime configuration differs from the reviewed manifest.')
    return {'image_id': image_id, 'reviewed_digest': actual,
            'changed_paths': len(proposal['paths']), 'status': 'explicit_content_review'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    draft = sub.add_parser('inspect'); draft.add_argument('image'); draft.add_argument('--output', required=True)
    approve = sub.add_parser('review'); approve.add_argument('manifest'); approve.add_argument('--digest', required=True)
    args = parser.parse_args()
    if args.command == 'inspect':
        review = inspect(args.image)
        path = Path(args.output)
        with path.open('x') as out:
            path.chmod(0o600); json.dump(review, out, indent=2, sort_keys=True); out.write('\n')
        summary = review['proposal']['summary']
        print(json.dumps(summary, indent=2))
        print('Pending review digest: '+review['proposal_digest'])
        print('Private manifest contains exact inherited runtime configuration; inspect it locally.')
        if summary['changed_paths'] > MAX_REVIEW_PATHS:
            raise SystemExit('Too large for this bounded review flow. No reviewed trust can be granted.')
    else:
        path = Path(args.manifest); review = json.loads(path.read_text())
        if args.digest != review.get('proposal_digest'):
            raise ValueError('Review digest must match the exact proposal.')
        review['reviewed_digest'] = args.digest
        validate(review, review['proposal']['image_id'])
        path.chmod(0o600); path.write_text(json.dumps(review, indent=2, sort_keys=True)+'\n')
        print('Explicit content review recorded. This is not a secret scan or provider execution.')


if __name__ == '__main__': main()
