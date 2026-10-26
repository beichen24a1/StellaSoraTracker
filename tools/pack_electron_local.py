"""Create a local review ZIP without modifying versions, manifests or releases."""
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'build/electron-package/win-unpacked'
OUT = ROOT/'release/StellaSoraGachaTool-Electron-local-win64.zip'
PRIVATE = {'exports', '.desktop', 'accounts', 'account_sessions', 'logs', 'updates', 'backups', '__pycache__'}
PRIVATE_NAMES = {'ui_settings.json','accounts.json','account.json','rem_upload_state.json','rem_upload_endpoint.txt',
                 'uid.json','fortune.json','server.json','archive_layout.json','stellasora_gacha_archive.json','.storage.lock','crash.log'}


def build_zip(source=SOURCE, target=OUT):
    source, target = Path(source), Path(target)
    if not (source/'StellaSoraGachaTool.exe').is_file():
        raise ValueError('Build the Electron application first')
    for name in ('resources/app.asar','resources/engine/StellaSoraEngine.exe','StellaSoraUpdater.exe',
                 'LICENSE','README.md','THIRD_PARTY_NOTICES.txt','LICENSE.electron.txt','LICENSES.chromium.html'):
        if not (source/name).is_file():
            raise ValueError(f'Missing distribution file: {name}')
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=target.parent, suffix='.zip.part'); os.close(descriptor)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(source.rglob('*')):
                if not path.is_file(): continue
                relative = path.relative_to(source)
                if PRIVATE.intersection(part.casefold() for part in relative.parts): continue
                if path.name.casefold() in PRIVATE_NAMES: continue
                if path.suffix.lower()=='.json' and path.stem.isdecimal(): continue
                archive.write(path, 'StellaSoraGachaTool/'+relative.as_posix())
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip(): raise ValueError('ZIP CRC check failed')
            names=archive.namelist()
            if any('pyside6' in item.casefold() or 'qt6core' in item.casefold() for item in names):
                raise ValueError('The Electron package must not carry Qt UI runtime')
        temporary.replace(target)
    finally: temporary.unlink(missing_ok=True)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.sha256').write_text(f'{digest}  {target.name}\n',encoding='ascii')
    return {'zip': str(target), 'bytes':target.stat().st_size, 'sha256':digest}


if __name__=='__main__': print(json.dumps(build_zip(),ensure_ascii=False,indent=2))
