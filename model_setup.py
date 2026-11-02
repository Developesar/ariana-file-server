"""Explicit one-time download; inference never downloads or contacts the network."""
from pathlib import Path
import hashlib
import json
import os

REPO = 'quickmt/quickmt-fa-en'
REVISION = '8faff595e128f8377c1de9371caef546c48fe4c2'
MODEL_DIR = Path(__file__).parent / 'models' / 'quickmt-fa-en'
FILES = ['config.json', 'model.bin', 'source_vocabulary.json', 'target_vocabulary.json',
         'src.spm.model', 'tgt.spm.model', 'README.md']
HASHES = {
    'model.bin': '091265c533b556b8c9d111519dd8142ff49e901256e35613876ce92679c91487',
    'src.spm.model': 'a0b876dcd23cce26a8b2dd35f3de1bea3dada039d27753498f5388960a97aa3f',
    'tgt.spm.model': '53931998683cf961ec8a9d3327deb4021d5bc12be2f2650758bb9a35dd828599',
}


def ready():
    return (MODEL_DIR / 'ready.json').is_file() and all((MODEL_DIR / f).is_file() for f in FILES)


def install(report=print):
    from huggingface_hub import snapshot_download
    report('Downloading pinned QuickMT Persian-English model (~410 MB)...')
    snapshot_download(REPO, revision=REVISION, local_dir=str(MODEL_DIR), allow_patterns=FILES,
                      max_workers=3, token=False)
    report('Verifying model checksums...')
    for name, expected in HASHES.items():
        digest = hashlib.sha256()
        with (MODEL_DIR / name).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError(f'Model checksum mismatch: {name}')
    marker = MODEL_DIR / 'ready.json'
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps({'repo': REPO, 'revision': REVISION, 'sha256': HASHES}, indent=2), encoding='utf-8')
    os.replace(temporary, marker)
    report('Model installed. Translation now works offline.')
    return str(MODEL_DIR)


if __name__ == '__main__':
    install()
