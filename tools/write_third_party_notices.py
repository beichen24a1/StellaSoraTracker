"""Collect distribution notices from installed build dependencies without running them."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT/'frontend'
OUT = ROOT/'build/THIRD_PARTY_NOTICES.txt'
parts = ['StellaSoraTracker · Third-party notices\n\nProject code: MIT, see LICENSE.\nGame artwork is not licensed under the project MIT license.\n\nThe entries below cover runtime components and build dependencies.\n']
lock = json.loads((FRONT/'package-lock.json').read_text('utf-8'))
for name, metadata in sorted(lock.get('packages', {}).items()):
    if not name.startswith('node_modules/'):
        continue
    directory = (FRONT/name).resolve()
    if FRONT.resolve() not in directory.parents:
        raise ValueError('Dependency path escapes frontend directory')
    label = name.removeprefix('node_modules/')
    parts.append(f'\n{"="*72}\n{label} {metadata.get("version", "")}\nLicense: {metadata.get("license", "See package notice")}\n')
    if directory.is_dir():
        for file in sorted(directory.iterdir()):
            if file.is_file() and file.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')):
                parts.append(f'\n--- {file.name} ---\n'+file.read_text('utf-8', errors='replace'))
python_license = Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():
    parts.append('\n'+'='*72+'\nPython runtime\n'+python_license.read_text('utf-8', errors='replace'))
try:
    import PyInstaller
    for file in (Path(PyInstaller.__file__).parent.parent).glob('pyinstaller-*.dist-info/licenses/*'):
        if file.is_file(): parts.append('\nPyInstaller bootloader/build license\n'+file.read_text('utf-8', errors='replace'))
except ImportError:
    pass
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text('\n'.join(parts), encoding='utf-8')
print(f'Third-party notices: {OUT.stat().st_size} bytes')
