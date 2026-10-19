"""打包后瘦身: 砍掉内嵌 Chromium 带来的无用大件。

QtWebEngine 让包体从 ~250MB 涨到 ~615MB, 其中真正必需的只有:
    Qt6WebEngineCore.dll / Qt6WebEngineWidgets.dll / QtWebEngineProcess.exe /
    icudtl.dat / qtwebengine_resources*.pak
可以安全删掉:
    - qtwebengine_devtools_resources*.pak   调试器前端(只在开 DevTools 时用)
    - translations/ 里除中文/英文以外的翻译
    - numpy / scipy 相关                    本工具不 import 它们(PIL 只按需用)
**不要删 qml/**: QtWebEngine 初始化时会用到里面的 QML 模块, 删掉后内嵌浏览器会
只显示空白页(踩过一次)。


用法(在 pack_release 之前):
    python tools/trim_bundle.py [--src release/github/StellaSoraGachaTool]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "release" / "github" / "StellaSoraGachaTool"

# 只保留中文/英文翻译, 其余语言删掉(文件形如 qtwebengine_zh_CN.qm / qtbase_ja.qm)
KEEP_TRANSLATION_SUFFIXES = ("_zh_CN.qm", "_en.qm", "_zh_TW.qm")


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def trim(src: Path) -> list[tuple[str, float]]:
    """返回 [(删掉的东西, 节省的 MB)]。"""
    internal = src / "_internal"
    if not internal.is_dir():
        raise SystemExit(f"未找到构建输出: {src}（先跑 PyInstaller）")
    removed: list[tuple[str, float]] = []

    def drop(path: Path, reason: str = "") -> None:
        if not path.exists():
            return
        saved = _size(path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append((f"{path.relative_to(src)}{reason}", saved / 1024 / 1024))

    pyside = internal / "PySide6"
    # 1) DevTools 前端(最大的一块)
    for pak in pyside.glob("resources/qtwebengine_devtools_resources*.pak"):
        drop(pak, "  (DevTools)")
    # 3) 多余语言包
    translations = pyside / "translations"
    if translations.is_dir():
        for qm in translations.glob("*.qm"):
            if not qm.name.endswith(KEEP_TRANSLATION_SUFFIXES):
                drop(qm)
    # 4) 本工具用不到的数值库
    for pattern in ("numpy", "numpy.libs", "scipy", "scipy.libs"):
        for path in internal.glob(pattern):
            drop(path, "  (未使用)")
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="删掉构建产物里没用的大件")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    args = parser.parse_args(argv)
    src = args.src.resolve()
    before = _size(src)
    removed = trim(src)
    after = _size(src)
    for name, saved in removed:
        print(f"  - {name}  {saved:.1f} MB")
    print(f"{src.name}: {before / 1024 / 1024:.1f} MB → {after / 1024 / 1024:.1f} MB"
          f"（省 {(before - after) / 1024 / 1024:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
