"""Prepare an isolated extracted-package fixture; do not alter the delivered ZIP."""
import hashlib
import json
import tempfile
import zipfile
import re
from pathlib import Path
import pefile

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'release/StellaSoraGachaTool-Electron-local-win64.zip'
digest=hashlib.sha256(PACKAGE.read_bytes()).hexdigest()
fixture=Path(tempfile.mkdtemp(prefix='electron-package-qa-',dir=ROOT/'build'))/'中文 空格 验收'
fixture.mkdir()
with zipfile.ZipFile(PACKAGE) as archive:
    assert archive.testzip() is None
    names=archive.namelist()
    assert not any('pyside6' in name.lower() or '/exports/' in name.lower() or '/.desktop/' in name.lower() for name in names)
    for name in names:
        target=(fixture/name).resolve()
        assert fixture.resolve() in target.parents
    archive.extractall(fixture)
app_root=fixture/'StellaSoraGachaTool'
executable=app_root/'StellaSoraGachaTool.exe'
with pefile.PE(str(executable)) as image:
    manifests=[]
    for resource in image.DIRECTORY_ENTRY_RESOURCE.entries:
        if resource.id==24:
            for entry in resource.directory.entries:
                for language in entry.directory.entries:
                    item=language.data.struct
                    manifests.append((image.get_offset_from_rva(item.OffsetToData),image.get_data(item.OffsetToData,item.Size)))
# The client starts unelevated; reading the game asks for elevation at run time
# through the client's own prompt, so the manifest must not force UAC at launch.
assert any(re.search(br'level="asInvoker"', manifest) for _offset, manifest in manifests), \
    'Client manifest must start without an administrator token'
assert not any(b'requireAdministrator' in manifest for _offset, manifest in manifests), \
    'Client manifest must not force elevation at launch'
launcher=app_root/'启动器.exe'
assert launcher.is_file(), 'Launcher 启动器.exe must ship next to the client'
for name in ('LICENSE','README.md','THIRD_PARTY_NOTICES.txt','LICENSE.electron.txt','LICENSES.chromium.html'):
    assert (app_root/name).is_file(),name
assert (app_root/'resources/engine/StellaSoraEngine.exe').is_file()
report={'zip':str(PACKAGE),'sha256':digest,'fixture':str(app_root),'executable':str(executable),
        'launcher':str(launcher),'client_manifest':'asInvoker','elevation':'on demand','original_zip_unchanged':True}
(ROOT/'build/electron-package-fixture.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
