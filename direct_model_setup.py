"""Install/verify the pinned direct Dorna GGUF model. Inference never downloads."""
from pathlib import Path
import hashlib
import os


REPO = 'aeranginkaman/Dorna2-Llama3.1-8B-Instruct-Q4_K_M-GGUF'
REVISION = '0e6b14900c1598ad1ec89eb611fc062edd15bb46'
FILENAME = 'dorna2-llama3.1-8b-instruct-q4_k_m.gguf'
EXPECTED_SHA256 = '0c52df3f94ce5e723aa2752ec6440a2d0bcc4d07e281fc443e9144f66826b534'
MODEL_DIR = Path(__file__).parent / 'models' / 'dorna2'
MODEL_PATH = MODEL_DIR / FILENAME


def digest(path, report=print):
    sha = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            sha.update(chunk)
            done += len(chunk)
            if done % (512 * 1024 * 1024) < len(chunk):
                report(f'Verifying model: {done * 100 // size}%')
    return sha.hexdigest()


def install(report=print):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not MODEL_PATH.is_file():
        from huggingface_hub import hf_hub_download
        report('Downloading pinned Dorna 2 GGUF (~4.92 GB)...')
        downloaded = Path(hf_hub_download(
            repo_id=REPO, filename=FILENAME, revision=REVISION,
            local_dir=str(MODEL_DIR), token=False,
        ))
        if downloaded != MODEL_PATH:
            os.replace(downloaded, MODEL_PATH)
    report('Checking Dorna 2 SHA-256...')
    actual = digest(MODEL_PATH, report)
    if actual != EXPECTED_SHA256:
        raise RuntimeError(f'Model checksum mismatch: {actual}')
    report('Dorna 2 is ready for direct offline use.')
    return str(MODEL_PATH)


if __name__ == '__main__':
    install()
