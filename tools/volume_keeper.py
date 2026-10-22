"""盯着游戏进程，把它的音频会话音量钉在你设定的值上。

为什么需要：星塔旅人（国服 `xtlr.exe`）**不保存音频设置** —— PlayerPrefs 里只有
分辨率/渲染/游玩数据，没有 audio/volume 键，所以每次启动音量都回到默认；游戏内
把音量拉满也拦不住。这个工具在 Windows 层面（Core Audio 的 per-app 会话音量）
持续把它压回你要的值，Windows 本身会记住这个 per-app 音量，所以双保险。

用法：
    python tools/volume_keeper.py                 # 带托盘图标常驻（推荐）
    python tools/volume_keeper.py --headless      # 无界面常驻（开机自启用这个）
    python tools/volume_keeper.py --set 35        # 设为 35% 并保存（然后退出）
    python tools/volume_keeper.py --status        # 看配置 + 当前会话音量
    python tools/volume_keeper.py --install       # 写入开机自启(可选, 一般不需要)
    python tools/volume_keeper.py --uninstall     # 取消开机自启

    # 推荐: 跟启动器绑在一起(不常驻, 启动器退出就退出)
    python tools/volume_keeper.py --launch "<启动器 exe>"

配置与日志：%LOCALAPPDATA%\\StellaSoraVolume\\config.json / volume.log
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "StellaSoraVolume"
DEFAULT_EXES = ("xtlr.exe", "StellaSora.exe")     # 国服 / 国际服+日服
DEFAULT_VOLUME = 0.35
DEFAULT_INTERVAL = 1.5                            # 秒
TOLERANCE = 0.005                                 # 差超过 0.5% 才动手, 免得来回抖
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------- 配置

def config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def log_path() -> Path:
    return config_dir() / "volume.log"


@dataclass
class Config:
    exes: list[str] = field(default_factory=lambda: list(DEFAULT_EXES))
    volume: float = DEFAULT_VOLUME
    interval: float = DEFAULT_INTERVAL
    enabled: bool = True

    def clamped(self) -> "Config":
        self.volume = min(1.0, max(0.0, float(self.volume)))
        self.interval = max(0.3, float(self.interval))
        return self

    @classmethod
    def load(cls) -> "Config":
        try:
            payload = json.loads(config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        data = cls(
            exes=[str(x) for x in payload.get("exes") or DEFAULT_EXES],
            volume=float(payload.get("volume", DEFAULT_VOLUME)),
            interval=float(payload.get("interval", DEFAULT_INTERVAL)),
            enabled=bool(payload.get("enabled", True)),
        )
        return data.clamped()

    def save(self) -> bool:
        try:
            directory = config_dir()
            directory.mkdir(parents=True, exist_ok=True)
            config_path().write_text(
                json.dumps({"exes": self.exes, "volume": round(self.volume, 4),
                            "interval": self.interval, "enabled": self.enabled},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
            return True
        except OSError:
            return False


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    try:
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = log_path()
        if path.is_file() and path.stat().st_size > 1_000_000:
            path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


# ---------------------------------------------------------------- 音频会话

def _sessions():
    """当前默认输出设备上的所有音频会话（pycaw 封装 Core Audio）。"""
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetAllSessions()


def _process_name(session) -> str:
    process = getattr(session, "Process", None)
    if process is None:
        return ""
    try:
        return process.name()
    except Exception:                                  # noqa: BLE001  进程可能已退出
        return ""


def session_volumes(exes: list[str]) -> list[tuple[str, float]]:
    """[{exe 名, 当前音量}] —— 给 --status 用。"""
    found = []
    wanted = {name.casefold() for name in exes}
    for session in _sessions():
        name = _process_name(session)
        if name.casefold() not in wanted:
            continue
        try:
            volume = float(session.SimpleAudioVolume.GetMasterVolume())
        except Exception:                              # noqa: BLE001
            continue
        found.append((name, volume))
    return found


def enforce_once(config: Config) -> list[str]:
    """把匹配进程的会话音量压回目标值；返回实际改动过的记录。"""
    changes: list[str] = []
    wanted = {name.casefold() for name in config.exes}
    for session in _sessions():
        name = _process_name(session)
        if name.casefold() not in wanted:
            continue
        try:
            simple = session.SimpleAudioVolume
            current = float(simple.GetMasterVolume())
        except Exception:                              # noqa: BLE001
            continue
        if abs(current - config.volume) <= TOLERANCE:
            continue
        try:
            simple.SetMasterVolume(config.volume, None)
        except Exception as error:                     # noqa: BLE001
            changes.append(f"{name} 设置失败: {error}")
            continue
        changes.append(f"{name} {current:.0%} → {config.volume:.0%}")
    return changes


class Keeper(threading.Thread):
    """后台线程：每 interval 秒检查一次，游戏内被拉满就压回去。"""

    def __init__(self, config: Config):
        super().__init__(daemon=True, name="volume-keeper")
        self.config = config
        self._stop_event = threading.Event()
        self.last_changes: list[str] = []
        self.last_seen: float = time.time()

    def run(self) -> None:
        log(f"启动监视：进程 {', '.join(self.config.exes)} · 目标 {self.config.volume:.0%}"
            f" · 间隔 {self.config.interval}s")
        while not self._stop_event.is_set():
            if self.config.enabled:
                try:
                    changes = enforce_once(self.config)
                except Exception as error:             # noqa: BLE001
                    changes = [f"检查失败: {error}"]
                if changes:
                    self.last_changes = changes
                    self.last_seen = time.time()
                    for item in changes:
                        log(item)
            self._stop_event.wait(self.config.interval)

    def stop(self) -> None:
        self._stop_event.set()


# ---------------------------------------------------------------- 开机自启

def _autostart_command() -> str:
    """自启命令：打包后用 exe 自己，源码运行用 pythonw + 脚本。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --headless'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.is_file() else Path(sys.executable)
    return f'"{interpreter}" "{Path(__file__).resolve()}" --headless'


def install_autostart() -> bool:
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
        log(f"已写入开机自启：{_autostart_command()}")
        return True
    except OSError as error:
        log(f"写开机自启失败：{error}")
        return False


def uninstall_autostart() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        log("已取消开机自启")
        return True
    except FileNotFoundError:
        return True
    except OSError as error:
        log(f"取消自启失败：{error}")
        return False


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except (FileNotFoundError, OSError):
        return False


# ---------------------------------------------------------------- 托盘

def run_tray(config: Config) -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    keeper = Keeper(config)
    keeper.start()

    icon = QIcon(_make_icon())
    tray = QSystemTrayIcon(icon)
    menu = QMenu()

    header = QAction(f"目标音量 {config.volume:.0%}", menu)
    header.setEnabled(False)
    menu.addAction(header)
    menu.addSeparator()

    volume_actions = []
    for percent in (20, 35, 50, 70, 100):
        action = QAction(f"设为 {percent}%", menu, checkable=True)
        action.setChecked(abs(config.volume - percent / 100) < 0.005)
        action.triggered.connect(lambda _checked=False, p=percent: _choose(p))
        volume_actions.append(action)
        menu.addAction(action)
    menu.addSeparator()

    toggle = QAction("暂停监视", menu, checkable=True)
    toggle.setChecked(not config.enabled)
    toggle.triggered.connect(lambda checked: _toggle(checked))
    menu.addAction(toggle)

    autostart = QAction("开机自启", menu, checkable=True)
    autostart.setChecked(autostart_enabled())
    autostart.triggered.connect(lambda checked: _autostart(checked))
    menu.addAction(autostart)

    menu.addSeparator()
    menu.addAction(QAction("打开日志", menu, triggered=lambda: _open_log()))
    menu.addAction(QAction("重启监视", menu, triggered=lambda: _restart()))
    menu.addAction(QAction("退出", menu, triggered=lambda: (keeper.stop(), app.quit())))

    def _refresh_header() -> None:
        running = session_volumes(config.exes)
        if running:
            now = " · ".join(f"{name} {volume:.0%}" for name, volume in running)
            header.setText(f"目标 {config.volume:.0%}（当前 {now}）")
        else:
            header.setText(f"目标 {config.volume:.0%}（游戏未运行）")

    def _choose(percent: int) -> None:
        config.volume = percent / 100
        config.save()
        for action, value in zip(volume_actions, (20, 35, 50, 70, 100)):
            action.setChecked(value == percent)
        log(f"目标音量改为 {config.volume:.0%}")
        try:
            enforce_once(config)
        except Exception as error:                     # noqa: BLE001
            log(f"立即应用失败: {error}")
        _refresh_header()

    def _toggle(paused: bool) -> None:
        config.enabled = not paused
        config.save()
        toggle.setText("暂停监视" if not paused else "继续监视")
        header.setText(f"目标 {config.volume:.0%}（已暂停）" if paused
                       else f"目标 {config.volume:.0%}")
        log("已暂停监视" if paused else "已继续监视")

    def _autostart(checked: bool) -> None:
        ok = install_autostart() if checked else uninstall_autostart()
        if not ok:
            autostart.setChecked(not checked)

    def _open_log() -> None:
        try:
            os.startfile(log_path())                   # noqa: S606
        except OSError:
            pass

    def _restart() -> None:
        keeper.stop()
        threading.Thread(target=lambda: (time.sleep(0.2), None), daemon=True)
        fresh = Keeper(config)
        fresh.start()
        log("监视已重启")

    tray.setContextMenu(menu)
    tray.setToolTip(f"{APP_NAME} · 目标 {config.volume:.0%}")
    tray.show()
    timer = QTimer()
    timer.timeout.connect(_refresh_header)
    timer.start(3000)
    _refresh_header()
    log("托盘界面已就绪")
    return app.exec()


def _launch_with_tray(config: Config, target: str, extra_args: list[str]) -> int:
    """托盘模式 + 跟随启动器: 启动器退出后自动收摊。"""
    import subprocess
    from PySide6.QtCore import QTimer

    handle = acquire_single_instance()
    if handle is None:
        log(f"已有实例在运行, 只拉起启动器: {target}")
        try:
            subprocess.Popen([target, *extra_args])
            return 0
        except OSError as error:
            log(f"拉起启动器失败：{error}")
            return 1
    try:
        process = subprocess.Popen([target, *extra_args])
    except OSError as error:
        log(f"拉起启动器失败：{error}")
        return 1
    log(f"跟随启动器模式(托盘)：{target}")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()

    def poll() -> None:
        if process.poll() is None:
            return
        if _target_running(config.exes):
            return                                     # 启动器退了但游戏还在跑, 继续盯
        log("启动器与游戏都已退出, 关闭托盘")
        app.quit()

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(1000)
    return run_tray(config)


def _make_icon():
    """画一个简单的音符图标，免得依赖外部图片。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#3e6c86"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 60, 60)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI Symbol")
    font.setPixelSize(38)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "♪")
    painter.end()
    return pixmap


# ---------------------------------------------------------------- 单实例 / 跟随启动器

MUTEX_NAME = "StellaSoraVolume.SingleInstance"


def acquire_single_instance():
    """拿到命名互斥体就返回句柄(自己第一个), 已被占用返回 None。"""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if kernel32.GetLastError() == 183:                 # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return None
    return handle


def _target_running(exes: list[str]) -> bool:
    """目标进程(游戏)是否还在跑 —— 用 psutil, 不依赖会话。"""
    try:
        import psutil
    except ImportError:
        return False
    wanted = {name.casefold() for name in exes}
    for process in psutil.process_iter(["name"]):
        if process.pid == os.getpid():
            continue                                   # 别把自己算成游戏
        try:
            name = (process.info.get("name") or "").casefold()
        except Exception:                              # noqa: BLE001
            continue
        if name in wanted:
            return True
    return False


def launch_and_follow(config: Config, target: str, extra_args: list[str]) -> int:
    """拉起启动器并跟着它: 它退出, 我们就退出（不常驻）。

    已经有 keeper 在跑时, 只负责拉起启动器然后自己退出 —— 避免双开。
    """
    import subprocess
    handle = acquire_single_instance()
    if handle is None:
        log(f"已有实例在运行, 只拉起启动器: {target}")
        try:
            subprocess.Popen([target, *extra_args])
        except OSError as error:
            log(f"拉起启动器失败：{error}")
            return 1
        return 0
    keeper = Keeper(config)
    keeper.start()
    log(f"跟随启动器模式：{target}（进程 {', '.join(config.exes)} · 目标 {config.volume:.0%}）")
    try:
        process = subprocess.Popen([target, *extra_args])
    except OSError as error:
        log(f"拉起启动器失败：{error}")
        keeper.stop()
        return 1
    code = process.wait()
    log(f"启动器已退出(code={code}), 等游戏退出后再收摊")
    while _target_running(config.exes):
        time.sleep(1.0)
    log("游戏也已退出, 结束音量监视")
    keeper.stop()
    return 0


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把游戏进程的会话音量钉在设定值上")
    parser.add_argument("--exe", default="", help="要盯的进程名, 逗号分隔（默认 xtlr.exe,StellaSora.exe）")
    parser.add_argument("--set", type=float, default=None, help="目标音量 0-100")
    parser.add_argument("--interval", type=float, default=None, help="检查间隔秒数")
    parser.add_argument("--headless", action="store_true", help="无界面常驻")
    parser.add_argument("--once", action="store_true", help="只执行一次就退出")
    parser.add_argument("--status", action="store_true", help="显示配置与当前会话音量")
    parser.add_argument("--launch", default="", help="拉起这个程序(启动器)并跟着它, 它退出就退出")
    parser.add_argument("--no-tray", action="store_true", help="launch 模式下不显示托盘图标")
    parser.add_argument("--install", action="store_true", help="写入开机自启")
    parser.add_argument("--uninstall", action="store_true", help="取消开机自启")
    args = parser.parse_args(argv)

    config = Config.load()
    if args.exe:
        config.exes = [name.strip() for name in args.exe.split(",") if name.strip()]
    if args.set is not None:
        config.volume = args.set / 100 if args.set > 1 else args.set
        config.save()
        log(f"目标音量设为 {config.volume:.0%}")
        if args.set is not None and not (args.once or args.status or args.headless):
            print(f"目标音量已保存：{config.volume:.0%}")
            return 0
    if args.interval is not None:
        config.interval = args.interval
        config.save()
    config = config.clamped()

    if args.launch:
        target, _, tail = args.launch.partition("|")     # 用 | 分隔附加参数
        rest = [item for item in tail.split("|") if item] if tail else []
        if not args.no_tray and not args.headless:
            # 托盘模式下也要跟随启动器: 先起线程, 用定时器把启动器拉起来
            return _launch_with_tray(config, target.strip(), rest)
        return launch_and_follow(config, target.strip(), rest)
    if args.install:
        print("已写入开机自启" if install_autostart() else "写入开机自启失败")
        return 0
    if args.uninstall:
        print("已取消开机自启" if uninstall_autostart() else "取消开机自启失败")
        return 0
    if args.status:
        print(f"配置文件 : {config_path()}")
        print(f"目标进程 : {', '.join(config.exes)}")
        print(f"目标音量 : {config.volume:.0%}   间隔 {config.interval}s   "
              f"{'启用' if config.enabled else '已暂停'}")
        print(f"开机自启 : {'是' if autostart_enabled() else '否'}")
        running = session_volumes(config.exes)
        if running:
            for name, volume in running:
                print(f"当前会话 : {name} = {volume:.0%}")
        else:
            print("当前会话 : 没检测到目标进程在放声音")
        return 0
    if args.once:
        changes = enforce_once(config)
        print("\n".join(changes) if changes else "无需调整（或没检测到目标会话）")
        return 0
    if args.headless:
        keeper = Keeper(config)
        keeper.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            keeper.stop()
            return 0
    return run_tray(config)


if __name__ == "__main__":
    raise SystemExit(main())
