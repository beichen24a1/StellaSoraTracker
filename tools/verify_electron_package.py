"""Prepare an isolated extracted-package fixture; do not alter the delivered ZIP."""
import hashlib
import json
import subprocess
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
assert any(b'requireAdministrator' in manifest for _offset,manifest in manifests), 'Production manifest must request one administrator elevation'
# UAC's secure desktop cannot be automated. Only this disposable copy uses
# asInvoker so Playwright can exercise the exact packaged JS and frozen engine.
binary=bytearray(executable.read_bytes())
changed=False
for offset,manifest in manifests:
    match=re.search(br'level="requireAdministrator"',manifest)
    if match:
        replacement=b'level="asInvoker"'+b' '*(len(match[0])-len(b'level="asInvoker"'))
        binary[offset+match.start():offset+match.end()]=replacement
        changed=True
assert changed
executable.write_bytes(binary)
assert hashlib.sha256(PACKAGE.read_bytes()).hexdigest()==digest
for name in ('LICENSE','README.md','THIRD_PARTY_NOTICES.txt','LICENSE.electron.txt','LICENSES.chromium.html'):
    assert (app_root/name).is_file(),name
assert (app_root/'resources/engine/StellaSoraEngine.exe').is_file()
report={'zip':str(PACKAGE),'sha256':digest,'fixture':str(app_root),'executable':str(executable),
        'production_uac':'requireAdministrator','test_copy_uac':'asInvoker','original_zip_unchanged':True}
(ROOT/'build/electron-package-fixture.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
