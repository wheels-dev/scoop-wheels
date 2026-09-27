#!/usr/bin/env python3
"""Generate Scoop runtime URLs/hashes from the Wheels runtime pin."""
import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pin', default='https://raw.githubusercontent.com/wheels-dev/wheels/develop/tools/lucli.json')
parser.add_argument('--app', choices=['*', 'wheels', 'wheels-be'], default='*')
args = parser.parse_args()
if args.pin.startswith('https://'):
    with urllib.request.urlopen(args.pin) as response:
        pin = json.load(response)
else:
    pin = json.loads(Path(args.pin).read_text())
repo, version = pin['LUCLI_REPO'], pin['LUCLI_VERSION']
if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
    raise SystemExit('Invalid LUCLI_REPO')
if not re.fullmatch(r'\d+\.\d+\.\d+(\.\d+)?', version):
    raise SystemExit('Invalid LUCLI_VERSION')
url = f'https://github.com/{repo}/releases/download/v{version}/lucli-{version}.jar'
with urllib.request.urlopen(url) as response:
    hasher = hashlib.sha256()
    for chunk in iter(lambda: response.read(1024 * 1024), b''):
        hasher.update(chunk)
    digest = hasher.hexdigest()
# A stable local name keeps the wrapper independent of the selected version.
manifest_url = url + '#/lucli.jar'
for name in (['wheels', 'wheels-be'] if args.app == '*' else [args.app]):
    path = Path('bucket') / (name + '.json')
    original = path.read_text()
    manifest = json.loads(original)
    # Keep each manifest's own indentation so a runtime bump is a small diff.
    indent_match = re.search(r'^\{\n( +)"', original)
    indent = len(indent_match.group(1)) if indent_match else 2
    arch = manifest['architecture']['64bit']
    matches = [i for i, u in enumerate(arch['url']) if '/LuCLI/releases/' in u]
    if len(matches) != 1:
        raise SystemExit(f'{path}: expected exactly one LuCLI asset')
    index = matches[0]
    arch['url'][index] = manifest_url
    arch['hash'][index] = digest
    manifest['autoupdate']['architecture']['64bit']['url'][index] = manifest_url
    # The LuCLI entry's hash is pinned, not derived from $url, so autoupdate
    # must carry the same digest or a checkver -Update would write a stale one.
    auto_hash = manifest['autoupdate']['architecture']['64bit'].get('hash')
    if isinstance(auto_hash, list) and index < len(auto_hash):
        auto_hash[index] = digest
    manifest['pre_install'] = [re.sub(r'lucli-[0-9.]+\.bat', 'lucli.jar', line) for line in manifest['pre_install']]
    path.write_text(json.dumps(manifest, indent=indent, ensure_ascii=False) + '\n')
    print(f'{path}: {repo} {version} {digest}')
