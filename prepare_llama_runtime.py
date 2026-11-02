"""Replace an AVX-512 CPU plugin in the CUDA wheel with the official AVX2 CPU plugin."""
from pathlib import Path
import os
import sysconfig
import zipfile


VERSION = '0.3.35'
DOWNLOAD_DIR = Path(__file__).parent / '.runtime-download'
RUNTIME_DIR = Path(sysconfig.get_paths()['purelib']) / 'llama_cpp' / 'lib'


def install_avx2_plugin(report=print):
    matches = sorted(DOWNLOAD_DIR.glob(f'llama_cpp_python-{VERSION}-*-win_amd64.whl'))
    if not matches:
        raise RuntimeError('Official CPU wheel was not downloaded.')
    wheel = matches[-1]
    with zipfile.ZipFile(wheel) as archive:
        data = archive.read('llama_cpp/lib/ggml-cpu.dll')
    if len(data) < 500_000:
        raise RuntimeError('Downloaded AVX2 CPU plugin is unexpectedly small.')
    destination = RUNTIME_DIR / 'ggml-cpu.dll'
    temporary = destination.with_suffix('.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, destination)
    report(f'Installed official AVX2 CPU plugin: {len(data)} bytes')


if __name__ == '__main__':
    install_avx2_plugin()
