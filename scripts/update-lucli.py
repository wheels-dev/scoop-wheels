#!/usr/bin/env python3
"""Apply the Wheels LuCLI runtime pin to the Scoop manifests.

The pin is wheels-dev/wheels tools/lucli.json (LUCLI_REPO, LUCLI_VERSION,
LUCLI_SHA256.jar), the same one CI, Homebrew and the apt/yum packages use.

Scoop has no package revision: installed apps only update when the manifest
`version` changes. So the runtime is only moved together with a version
change (a new Wheels release, or the next develop snapshot), which the
autoupdate workflow's `checkver -Update` makes before calling this script.
A manifest whose version is unchanged from the committed one keeps its
runtime; --force skips that check (the smoke uses it on a scratch copy).
"""
import argparse
import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
parser.add_argument('--pin', default='https://raw.githubusercontent.com/wheels-dev/wheels/develop/tools/lucli.json')
parser.add_argument('--app', choices=['*', 'wheels', 'wheels-be'], default='*')
parser.add_argument('--bucket', default='bucket', help='directory holding the manifests')
parser.add_argument('--base-ref', default='HEAD', help='git ref whose manifest version counts as "unchanged"')
parser.add_argument('--force', action='store_true', help='apply the pin even if the version did not change')
args = parser.parse_args()

if args.pin.startswith('https://'):
    with urllib.request.urlopen(args.pin) as response:
        pin = json.load(response)
else:
    pin = json.loads(Path(args.pin).read_text())
repo, version = pin['LUCLI_REPO'], pin['LUCLI_VERSION']
pinned_sha = (pin.get('LUCLI_SHA256') or {}).get('jar', '')
if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
    raise SystemExit('Invalid LUCLI_REPO')
if not re.fullmatch(r'\d+\.\d+\.\d+(\.\d+)?', version):
    raise SystemExit('Invalid LUCLI_VERSION')
if not re.fullmatch(r'[0-9a-f]{64}', pinned_sha):
    raise SystemExit('tools/lucli.json has no valid LUCLI_SHA256.jar; refusing to touch the manifests')

url = f'https://github.com/{repo}/releases/download/v{version}/lucli-{version}.jar'
# A stable local name keeps the wrapper independent of the selected version.
manifest_url = url + '#/lucli.jar'


def committed_version(path):
    """The manifest version at --base-ref, or None when it cannot be read."""
    try:
        text = subprocess.run(
            ['git', 'show', f'{args.base_ref}:{path.as_posix()}'],
            capture_output=True, text=True, check=True,
        ).stdout
        return json.loads(text).get('version')
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


digest = None
for name in (['wheels', 'wheels-be'] if args.app == '*' else [args.app]):
    path = Path(args.bucket) / (name + '.json')
    original = path.read_text()
    manifest = json.loads(original)
    arch = manifest['architecture']['64bit']
    matches = [i for i, u in enumerate(arch['url']) if '/LuCLI/releases/' in u]
    if len(matches) != 1:
        raise SystemExit(f'{path}: expected exactly one LuCLI asset')
    index = matches[0]
    if arch['url'][index] == manifest_url and arch['hash'][index] == pinned_sha:
        print(f'{path}: already on {repo} {version}')
        continue
    if not args.force and committed_version(path) == manifest.get('version'):
        print(f'{path}: version {manifest.get("version")} unchanged; the runtime moves with the next version bump')
        continue

    if digest is None:
        with urllib.request.urlopen(url) as response:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                hasher.update(chunk)
            digest = hasher.hexdigest()
        if digest != pinned_sha:
            raise SystemExit(f'{url} is {digest}, but the pin says {pinned_sha}; refusing to update the manifests')

    arch['url'][index] = manifest_url
    arch['hash'][index] = digest
    manifest['autoupdate']['architecture']['64bit']['url'][index] = manifest_url
    # The LuCLI entry's hash is pinned, not derived from $url, so autoupdate
    # must carry the same digest or a checkver -Update would write a stale one.
    auto_hash = manifest['autoupdate']['architecture']['64bit'].get('hash')
    if isinstance(auto_hash, list) and index < len(auto_hash):
        auto_hash[index] = digest
    manifest['pre_install'] = [re.sub(r'lucli-[0-9.]+\.bat', 'lucli.jar', line) for line in manifest['pre_install']]
    # Keep each manifest's own indentation so a runtime bump is a small diff.
    indent_match = re.search(r'^\{\n( +)"', original)
    indent = len(indent_match.group(1)) if indent_match else 2
    path.write_text(json.dumps(manifest, indent=indent, ensure_ascii=False) + '\n')
    print(f'{path}: {repo} {version} {digest}')
