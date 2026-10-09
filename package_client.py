#!/usr/bin/env python3
"""Package only built public client code and notices; configuration is delivered separately."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    output=args.output.expanduser().resolve()
    if output.is_relative_to(ROOT):p.error('Use an output directory outside the checkout')
    if not (ROOT/'web/dist/index.html').is_file():p.error('Build web first: npm ci && npm run build')
    files=[ROOT/name for name in ('viewer.py','LICENSE','THIRD_PARTY_NOTICES.md','README.md')]
    files+=sorted(f for directory in ('web/dist','third_party','docs') for f in (ROOT/directory).rglob('*') if f.is_file())
    if any(f.is_symlink() for f in files):p.error('Public bundle contains a symlink')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for f in files:archive.write(f,str(f.relative_to(ROOT)))
        archive.writestr('manifest.json',json.dumps({str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files},indent=2))
    print(output)


if __name__=='__main__':main()
