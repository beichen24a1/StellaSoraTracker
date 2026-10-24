"""Optional uploads after a successful read/import and cancellable software updates."""
from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from .. import app_updater, rem_upload
from ..service import export_share_for_uid
from .constants import APP_VERSION
from .preferences import load_automation, save_automation


@dataclass(frozen=True)
class UpdateReply:
    value: object
    automatic: bool
    generation: int
    update: object = None


class AutomationMixin:
    def _init_automation(self):
        self.automation = load_automation(self.output)
        self._pending_uploads = {}
        self._upload_timer = QTimer(self)
        self._upload_timer.setSingleShot(True)
        self._upload_timer.timeout.connect(self._run_pending_upload)
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._automatic_update)
        self._install_timer = QTimer(self)
        self._install_timer.setSingleShot(True)
        self._install_timer.timeout.connect(self._offer_update)
        self._update_state = 'idle'
        self._update_generation = 0
        self._update_automatic = False
        self._update_cancel = threading.Event()
        self._ready_update = None
        self._available_update = None
        self._installing_update = False

    def _set_automation(self, key, enabled):
        checkbox = self.automation_checks[key]
        if not save_automation(self.output, key, enabled):
            checkbox.blockSignals(True)
            checkbox.setChecked(self.automation[key])
            checkbox.blockSignals(False)
            self.status('设置保存失败，开关未改变。')
            return
        self.automation[key] = enabled
        if key == 'auto_upload':
            if not enabled:
                self._pending_uploads.clear()
                self._upload_timer.stop()
            self.status('已开启自动上传，下次抓取或导入新记录后上传到蕾姆。' if enabled
                        else '自动上传已关闭，仍可在「上传与分享」手动上传。')
        elif enabled:
            self._schedule_update_check()
            self.update_status.setText('自动更新已开启：启动时检查，下载前询问，校验后再次确认安装。')
        else:
            self._update_timer.stop()
            if self._update_automatic:
                self._update_cancel.set()
                self._update_generation += 1
                self._update_state = 'idle'
                self._install_timer.stop()
                self._available_update = None
                if self._ready_update:
                    self._discard_package(self._ready_update.value)
                    self._ready_update = None
                self.restart_update_button.hide()
            self.update_status.setText('自动更新已关闭；仍可手动检查更新。')

    def _queue_auto_upload(self, path):
        if self.demo or not self.online_sync or not self.automation['auto_upload'] or not path:
            return
        path = Path(path)
        self._pending_uploads[str(path.resolve())] = path
        self._upload_timer.start(250)

    def _run_pending_upload(self):
        if self.demo or not self.online_sync or not self.automation['auto_upload']:
            self._pending_uploads.clear()
            return
        if not self._pending_uploads:
            return
        if self._busy:
            self._upload_timer.start(500)
            return
        key = next(iter(self._pending_uploads))
        path = self._pending_uploads.pop(key)
        self._rem_upload(automatic=True, path=path)
        if self._pending_uploads:
            self._upload_timer.start(500)

    def _rem_upload(self, *, automatic=False, path=None):
        if self.demo or self._busy:
            return
        try:
            path = Path(path) if path else export_share_for_uid(self._output_dir)
            fingerprint = rem_upload.record_fingerprint(path)
            endpoint = rem_upload.UPLOAD_URL
            if automatic and rem_upload.was_uploaded(path, fingerprint, endpoint):
                self._account_note(f'UID {path.stem} 的记录没有变化，已跳过重复上传。')
                return
        except (OSError, ValueError, rem_upload.RemUploadError) as error:
            self._account_note(f'无法上传：{error}')
            return
        self._account_note(f'正在{"自动" if automatic else ""}上传 UID {path.stem} 到蕾姆…')
        self._set_busy(True)

        def work():
            try:
                result = rem_upload.upload_file(path, endpoint=endpoint)
                try:
                    first = rem_upload.mark_uploaded(path.parent, result.uid,
                                                     fingerprint=fingerprint, endpoint=endpoint)
                    state_error = ''
                except (OSError, ValueError) as error:
                    first, state_error = True, str(error)
                payload = (result, first, state_error)
            except Exception as error:
                payload = error
            self._bridge.account.emit('rem_upload', payload)

        threading.Thread(target=work, name='stellasora-rem-upload', daemon=True).start()

    def _on_account_result(self, action, payload):
        super()._on_account_result(action, payload)
        if action == 'rem_upload' and not isinstance(payload, Exception):
            result, _first, error = payload
            note = (f'UID {result.uid} 上传成功，已暂存到蕾姆。\n'
                    f'仍需发送绑定指令确认更新：{result.bind_command}')
            if error:
                note += f'\n上传成功状态未能保存，下次可能重复上传：{error}'
            self._account_note(note)
        if self._pending_uploads:
            self._upload_timer.start(250)

    def _schedule_update_check(self):
        if (not self.demo and self.online_sync and getattr(sys, 'frozen', False)
                and self.automation['auto_update']):
            self._update_timer.start(1600)

    def _automatic_update(self):
        if not self.automation['auto_update'] or self.demo or not self.online_sync:
            return
        if not getattr(sys, 'frozen', False):
            return
        if self._busy:
            self._update_timer.start(5000)
            return
        self._start_update_check(automatic=True)

    def _check_update(self):
        if self._update_state in ('available', 'ready'):
            self._offer_update()
            return
        self._start_update_check(automatic=False)

    def _start_update_check(self, *, automatic):
        if self.demo or self._busy or self._update_state != 'idle':
            return
        self._update_generation += 1
        generation = self._update_generation
        self._update_automatic = automatic
        self._update_cancel = threading.Event()
        self._update_state = 'checking'
        self.update_status.setText('正在检查 GitHub 软件更新…')

        def work():
            try:
                value = app_updater.check_for_update(app_updater.update_urls(), APP_VERSION)
            except Exception as error:
                value = error
            self.update_result.emit(UpdateReply(value, automatic, generation))

        threading.Thread(target=work, name='stellasora-update-check', daemon=True).start()

    def _update_checked(self, reply):
        if not isinstance(reply, UpdateReply):
            reply = UpdateReply(reply, False, self._update_generation)
        if reply.generation != self._update_generation:
            return
        result = reply.value
        self._update_state = 'idle'
        if isinstance(result, Exception):
            self.update_status.setText(f'检查更新失败：{result}')
            if not reply.automatic:
                self.status(f'检查更新失败：{result}')
            return
        if result is None:
            self.update_status.setText(f'当前已是最新版 v{APP_VERSION}。')
            if not reply.automatic:
                self.status(f'当前已是最新版 v{APP_VERSION}。')
            return
        if not getattr(sys, 'frozen', False):
            self.update_status.setText(f'发现 v{result.version}；源码模式请下载发行包。')
            if QMessageBox.question(self, '发现新版本',
                    f'v{result.version}\n{result.notes}\n\n打开下载地址？') == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(result.url))
            return
        self._available_update = reply
        self._update_state = 'available'
        self.update_status.setText(f'发现 v{result.version}，等待确认是否下载。')
        self._install_timer.start(250)

    def _download_app_update(self, update, automatic, generation):
        self._update_state = 'downloading'
        self.update_status.setText(f'正在下载并校验 v{update.version}…')
        cancel = self._update_cancel

        def work():
            try:
                value = app_updater.download_update(update, self.output / 'updates',
                                                     cancelled=cancel.is_set)
            except Exception as error:
                value = error
            self.update_package.emit(UpdateReply(value, automatic, generation, update))

        threading.Thread(target=work, name='stellasora-update-download', daemon=True).start()

    def _install_update(self, reply):
        if reply.generation != self._update_generation:
            self._discard_package(reply.value)
            return
        if isinstance(reply.value, Exception):
            self._update_state = 'idle'
            self.update_status.setText(f'下载更新失败：{reply.value}')
            return
        if not Path(reply.value).is_file():
            self._update_state = 'idle'
            self.update_status.setText('更新包不存在，请重新检查更新。')
            return
        self._ready_update = reply
        self._update_state = 'ready'
        self.update_status.setText(f'v{reply.update.version} 已下载并通过 SHA-256 校验，可重启安装。')
        self.restart_update_button.show()
        self._install_timer.start(250)

    def _offer_update(self):
        available = self._available_update
        if available is not None:
            if self._busy:
                self._install_timer.start(1000)
                return
            self._available_update = None
            if QMessageBox.question(self, '发现软件更新',
                    f'v{available.value.version}\n{available.value.notes}\n\n是否下载更新？下载后仍需确认安装。') != QMessageBox.Yes:
                self._update_state = 'idle'
                return
            self._download_app_update(available.value, available.automatic, available.generation)
            return
        reply = self._ready_update
        if reply is None:
            return
        if self._busy:
            self._install_timer.start(1000)
            return
        if QMessageBox.question(self, '软件更新已就绪',
                f'v{reply.update.version} 已下载并通过校验。\n\n现在重启并安装？本地归档与设置会保留。'
                '\n选择“否”后可在「数据与设置」重启更新。') != QMessageBox.Yes:
            return
        self._restart_for_update()

    def _restart_for_update(self):
        if self._busy or self._ready_update is None:
            return
        try:
            app_updater.launch_update_installer(self._ready_update.value, Path(sys.executable))
        except (OSError, ValueError) as error:
            self.update_status.setText(f'启动更新失败：{error}')
            return
        self._installing_update = True
        self._stop_automation()
        self._ready_update = None
        QTimer.singleShot(0, self.close)

    @staticmethod
    def _discard_package(value):
        if isinstance(value, Path):
            try:
                value.unlink(missing_ok=True)
            except OSError:
                pass

    def _stop_automation(self):
        self._upload_timer.stop()
        self._update_timer.stop()
        self._install_timer.stop()
        self._update_cancel.set()
        self._update_generation += 1
        self._pending_uploads.clear()
