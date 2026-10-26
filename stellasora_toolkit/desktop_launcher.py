"""Default source launcher for the Electron client. The Qt entry stays available separately."""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description='星塔旅人 Electron 桌面客户端')
    parser.add_argument('--output',type=Path,default=root/'exports')
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args(argv)
    executable=root/'frontend/node_modules/electron/dist/electron.exe'
    compiled=root/'frontend/dist-electron/main.cjs'
    if not executable.is_file() or not compiled.is_file():
        print('请先运行 run_electron.ps1 安装并构建客户端；旧 Qt 对照入口为 run_qt_legacy.ps1。',file=sys.stderr)
        return 1
    environment=dict(os.environ,STELLA_OUTPUT=str(args.output.resolve()),STELLA_PROFILE=str(root/'build/electron-preview-profile'))
    for key in ('ELECTRON_RUN_AS_NODE','NODE_OPTIONS'):
        environment.pop(key,None)
    if args.offline:environment['STELLA_OFFLINE']='1'
    result=subprocess.run([str(executable),'.'],cwd=root/'frontend',env=environment)
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
