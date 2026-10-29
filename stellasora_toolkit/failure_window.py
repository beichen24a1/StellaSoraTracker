"""Self-drawn updater failure UI; works without Electron, Qt, Tcl or a browser."""
from __future__ import annotations

import ctypes
import json
import os
import re
from ctypes import wintypes as w
from pathlib import Path


def presentation(message: str, settings_path: Path | None = None) -> tuple[str, dict[str, str]]:
    dark = False
    try:
        prefs = json.loads(settings_path.read_text('utf-8')) if settings_path else {}
        dark = prefs.get('color_mode') == 'dark' or (not prefs.get('color_mode') and prefs.get('theme') == 'orbit')
    except (OSError, ValueError, AttributeError):
        pass
    colors = dict(zip(('bg', 'surface', 'text', 'muted', 'line', 'primary', 'soft'),
        ('10151c', '1a222d', 'e4ecf5', '96a8ba', '303e4e', '78b8df', '233c50') if dark else
        ('f2f7fb', 'ffffff', '243b4d', '7890a2', 'dfe9f0', '23769a', 'e7f2f8')))
    return re.sub(r'https?://\S+', '[服务地址]', str(message))[:16000], colors


def show_failure(message: str, *, log_path: Path, settings_path: Path | None = None) -> None:
    if os.name != 'nt':
        return
    text, colors = presentation(message, settings_path)
    _FailureWindow(text, colors, log_path).run()


class _FailureWindow:
    def __init__(self, text, colors, log_path):
        self.text, self.colors, self.log_path = text, colors, Path(log_path)
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.g = ctypes.WinDLL('gdi32', use_last_error=True)
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        pointer = ctypes.c_void_p
        result = ctypes.c_ssize_t
        self.callback_type = ctypes.WINFUNCTYPE(result, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WindowClass(ctypes.Structure):
            _fields_ = [('size', w.UINT), ('style', w.UINT), ('proc', self.callback_type),
                        ('classExtra', ctypes.c_int), ('windowExtra', ctypes.c_int), ('instance', w.HINSTANCE),
                        ('icon', w.HICON), ('cursor', w.HANDLE), ('background', w.HBRUSH),
                        ('menu', w.LPCWSTR), ('name', w.LPCWSTR), ('smallIcon', w.HICON)]

        class Paint(ctypes.Structure):
            _fields_ = [('dc', w.HDC), ('erase', w.BOOL), ('rect', w.RECT), ('restore', w.BOOL),
                        ('update', w.BOOL), ('reserved', w.BYTE * 32)]

        class DrawItem(ctypes.Structure):
            _fields_ = [('type', w.UINT), ('id', w.UINT), ('item', w.UINT), ('action', w.UINT),
                        ('state', w.UINT), ('window', w.HWND), ('dc', w.HDC), ('rect', w.RECT), ('data', ctypes.c_size_t)]

        self.WindowClass, self.Paint, self.DrawItem = WindowClass, Paint, DrawItem
        signatures = [
            (self.k, 'GetModuleHandleW', [w.LPCWSTR], w.HINSTANCE),
            (self.k, 'GlobalAlloc', [w.UINT, ctypes.c_size_t], pointer),
            (self.k, 'GlobalLock', [pointer], pointer), (self.k, 'GlobalUnlock', [pointer], w.BOOL),
            (self.k, 'GlobalFree', [pointer], pointer),
            (self.u, 'RegisterClassExW', [ctypes.POINTER(WindowClass)], w.ATOM),
            (self.u, 'UnregisterClassW', [w.LPCWSTR, w.HINSTANCE], w.BOOL),
            (self.u, 'CreateWindowExW', [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, pointer], w.HWND),
            (self.u, 'DefWindowProcW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], result),
            (self.u, 'DestroyWindow', [w.HWND], w.BOOL),
            (self.u, 'ShowWindow', [w.HWND, ctypes.c_int], w.BOOL),
            (self.u, 'SetForegroundWindow', [w.HWND], w.BOOL),
            (self.u, 'UpdateWindow', [w.HWND], w.BOOL),
            (self.u, 'GetMessageW', [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT], w.BOOL),
            (self.u, 'TranslateMessage', [ctypes.POINTER(w.MSG)], w.BOOL),
            (self.u, 'DispatchMessageW', [ctypes.POINTER(w.MSG)], result),
            (self.u, 'IsDialogMessageW', [w.HWND, ctypes.POINTER(w.MSG)], w.BOOL),
            (self.u, 'GetFocus', [], w.HWND), (self.u, 'SetFocus', [w.HWND], w.HWND),
            (self.u, 'SendMessageW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], result),
            (self.u, 'PostMessageW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
            (self.u, 'BeginPaint', [w.HWND, ctypes.POINTER(Paint)], w.HDC),
            (self.u, 'EndPaint', [w.HWND, ctypes.POINTER(Paint)], w.BOOL),
            (self.u, 'GetClientRect', [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            (self.u, 'ScreenToClient', [w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
            (self.u, 'MoveWindow', [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.BOOL], w.BOOL),
            (self.u, 'InvalidateRect', [w.HWND, ctypes.POINTER(w.RECT), w.BOOL], w.BOOL),
            (self.u, 'FillRect', [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH], ctypes.c_int),
            (self.u, 'DrawTextW', [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT], ctypes.c_int),
            (self.u, 'DrawFocusRect', [w.HDC, ctypes.POINTER(w.RECT)], w.BOOL),
            (self.u, 'LoadCursorW', [w.HINSTANCE, pointer], w.HANDLE),
            (self.u, 'LoadIconW', [w.HINSTANCE, pointer], w.HICON),
            (self.u, 'OpenClipboard', [w.HWND], w.BOOL), (self.u, 'EmptyClipboard', [], w.BOOL),
            (self.u, 'CloseClipboard', [], w.BOOL), (self.u, 'SetClipboardData', [w.UINT, pointer], pointer),
            (self.g, 'CreateSolidBrush', [w.DWORD], w.HBRUSH),
            (self.g, 'CreatePen', [ctypes.c_int, ctypes.c_int, w.DWORD], pointer),
            (self.g, 'SelectObject', [w.HDC, pointer], pointer),
            (self.g, 'DeleteObject', [pointer], w.BOOL),
            (self.g, 'SetTextColor', [w.HDC, w.DWORD], w.DWORD),
            (self.g, 'SetBkColor', [w.HDC, w.DWORD], w.DWORD),
            (self.g, 'SetBkMode', [w.HDC, ctypes.c_int], ctypes.c_int),
            (self.g, 'RoundRect', [w.HDC]+[ctypes.c_int]*6, w.BOOL),
            (self.g, 'CreateFontW', [ctypes.c_int]*5+[w.DWORD]*8+[w.LPCWSTR], pointer),
        ]
        for library, name, args, returns in signatures:
            function = getattr(library, name)
            function.argtypes, function.restype = args, returns
        try:
            self.u.SetProcessDPIAware()
            self.scale = self.u.GetDpiForSystem()/96
        except AttributeError:
            self.scale = 1
        self.brushes = {key: self.g.CreateSolidBrush(self.color(key)) for key in colors}
        self.fonts = {size: self.g.CreateFontW(-self.px(size), 0, 0, 0, 600 if size >= 20 else 400,
                     0, 0, 0, 1, 0, 0, 5, 0, 'Segoe UI') for size in (10, 11, 12, 13, 25, 28)}
        self.buttons = {}
        self.edit = None
        self.status = ''
        self.callback_error = None
        self.callback = self.callback_type(self.window_proc)
        self.instance = self.k.GetModuleHandleW(None)
        self.class_name = f'StellaSoraFailure-{os.getpid()}'

    def px(self, value):
        return round(value*self.scale)

    def color(self, key):
        value = self.colors[key]
        return int(value[:2], 16) | int(value[2:4], 16) << 8 | int(value[4:], 16) << 16

    def label(self, dc, text, rect, *, size=12, color='text', flags=0):
        previous = self.g.SelectObject(dc, self.fonts[size])
        self.g.SetTextColor(dc, self.color(color))
        self.g.SetBkMode(dc, 1)
        self.u.DrawTextW(dc, text, -1, ctypes.byref(w.RECT(*map(self.px, rect))), flags)
        self.g.SelectObject(dc, previous)

    def round_rect(self, dc, rect, fill='surface', border='line', radius=10, *, scaled=True):
        points = list(map(self.px, rect)) if scaled else list(rect)
        brush = self.g.SelectObject(dc, self.brushes[fill])
        pen = self.g.CreatePen(0, 1, self.color(border))
        previous_pen = self.g.SelectObject(dc, pen)
        self.g.RoundRect(dc, *points, self.px(radius), self.px(radius))
        self.g.SelectObject(dc, previous_pen)
        self.g.SelectObject(dc, brush)
        self.g.DeleteObject(pen)

    def paint(self, hwnd):
        paint = self.Paint()
        dc = self.u.BeginPaint(hwnd, ctypes.byref(paint))
        try:
            self.paint_contents(hwnd, dc)
        finally:
            self.u.EndPaint(hwnd, ctypes.byref(paint))

    def paint_contents(self, hwnd, dc):
        client = w.RECT()
        self.u.GetClientRect(hwnd, ctypes.byref(client))
        width, height = client.right/self.scale, client.bottom/self.scale
        self.u.FillRect(dc, ctypes.byref(client), self.brushes['bg'])
        self.label(dc, 'STELLA SORA · RECOVERY', (28, 17, width-70, 37), size=10, color='muted')
        self.round_rect(dc, (32, 76, 82, 126), 'soft', 'soft', 14)
        self.label(dc, '!', (32, 80, 82, 121), size=28, color='primary', flags=1)
        self.label(dc, '更新未完成', (98, 73, width-32, 110), size=25)
        self.label(dc, '错误详情与日志已保留。可以复制信息后反馈，或打开日志目录查看。',
                   (98, 119, width-33, 162), size=12, color='muted', flags=0x10)
        self.round_rect(dc, (32, 178, width-32, height-108))
        self.label(dc, '错误详情', (50, 194, width-50, 215), size=12)
        self.label(dc, self.status, (34, height-32, width-32, height-10), size=11, color='muted')

    def layout(self, hwnd):
        if not self.edit:
            return
        rect = w.RECT()
        self.u.GetClientRect(hwnd, ctypes.byref(rect))
        width, height = rect.right/self.scale, rect.bottom/self.scale
        controls = {self.edit: (50, 225, width-100, height-351)}
        positions = {2: (width-49, 9, 32, 30), 101: (32, height-79, 145, 38),
                     100: (width-250, height-79, 112, 38), 1: (width-126, height-79, 94, 38)}
        controls.update({handle: positions[identifier] for handle, identifier in self.buttons.items()})
        for handle, bounds in controls.items():
            self.u.MoveWindow(handle, *map(self.px, bounds), True)

    def draw_button(self, item):
        rect = item.rect
        self.u.FillRect(item.dc, ctypes.byref(rect), self.brushes['bg'])
        bounds = (rect.left+1, rect.top+1, rect.right-1, rect.bottom-1)
        primary = item.id == 1
        fill = 'bg' if item.id == 2 else 'primary' if primary else 'soft' if item.state & 1 else 'surface'
        self.round_rect(item.dc, bounds, fill, 'bg' if item.id == 2 else 'primary' if primary else 'line', scaled=False)
        text = {1: '关闭', 2: '×', 100: '复制详情', 101: '打开日志目录'}[item.id]
        font = self.g.SelectObject(item.dc, self.fonts[12])
        self.g.SetBkMode(item.dc, 1)
        self.g.SetTextColor(item.dc, self.color('bg' if primary else 'text'))
        self.u.DrawTextW(item.dc, text, -1, ctypes.byref(rect), 1 | 4 | 0x20)
        self.g.SelectObject(item.dc, font)
        if item.state & 0x10:
            inset = w.RECT(rect.left+4, rect.top+4, rect.right-4, rect.bottom-4)
            self.u.DrawFocusRect(item.dc, ctypes.byref(inset))

    def copy(self, hwnd):
        data = (self.text+'\0').encode('utf-16-le')
        handle = self.k.GlobalAlloc(2, len(data))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        address = self.k.GlobalLock(handle)
        if not address:
            self.k.GlobalFree(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(address, data, len(data))
        self.k.GlobalUnlock(handle)
        transferred = False
        try:
            if not self.u.OpenClipboard(hwnd):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not self.u.EmptyClipboard() or not self.u.SetClipboardData(13, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                transferred = True
            finally:
                self.u.CloseClipboard()
        finally:
            if not transferred:
                self.k.GlobalFree(handle)

    def activate(self, hwnd, identifier):
        if identifier in (1, 2):
            self.u.DestroyWindow(hwnd)
            return
        try:
            if identifier == 100:
                self.copy(hwnd)
                self.status = '错误详情已复制'
            elif identifier == 101:
                os.startfile(str(self.log_path.resolve().parent))
                self.status = '已打开日志目录'
        except OSError:
            self.status = '操作未完成，请稍后重试。错误信息仍保留在本页。'
        self.u.InvalidateRect(hwnd, None, False)

    def window_proc(self, hwnd, message, wp, lp):
        try:
            if message == 0xF:  # WM_PAINT
                self.paint(hwnd)
                return 0
            if message == 0x318:  # WM_PRINTCLIENT (window previews and diagnostics)
                self.paint_contents(hwnd, wp)
                return 0
            if message == 0x14:  # WM_ERASEBKGND
                return 1
            if message == 5:
                self.layout(hwnd)
                return 0
            if message == 0x2B:  # WM_DRAWITEM: real accessible buttons, with our own rendering.
                self.draw_button(ctypes.cast(lp, ctypes.POINTER(self.DrawItem)).contents)
                return 1
            if message in (0x133, 0x138):  # edit/static text colors
                self.g.SetTextColor(wp, self.color('muted'))
                self.g.SetBkColor(wp, self.color('surface'))
                return self.brushes['surface']
            if message == 0x111:
                self.activate(hwnd, wp & 0xffff)
                return 0
            if message == 0x84:  # Drag the custom title area without a Windows caption.
                point = w.POINT(ctypes.c_short(lp & 0xffff).value, ctypes.c_short(lp >> 16 & 0xffff).value)
                self.u.ScreenToClient(hwnd, ctypes.byref(point))
                if point.y < self.px(46) and point.x < self.px(640):
                    return 2
            if message == 0x10:
                self.u.DestroyWindow(hwnd)
                return 0
            if message == 2:
                self.u.PostQuitMessage(0)
                return 0
            return self.u.DefWindowProcW(hwnd, message, wp, lp)
        except BaseException as error:
            self.callback_error = error
            self.u.PostMessageW(hwnd, 0x10, 0, 0)
            return 0

    def run(self):
        wc = self.WindowClass()
        wc.size, wc.proc, wc.instance, wc.name = ctypes.sizeof(wc), self.callback, self.instance, self.class_name
        wc.cursor = self.u.LoadCursorW(None, ctypes.c_void_p(32512))
        wc.icon = self.u.LoadIconW(self.instance, ctypes.c_void_p(1))
        if not self.u.RegisterClassExW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            width, height = self.px(700), self.px(550)
            x = max(0, (self.u.GetSystemMetrics(0)-width)//2)
            y = max(0, (self.u.GetSystemMetrics(1)-height)//2)
            hwnd = self.u.CreateWindowExW(0x40000 | 0x10000, self.class_name, '星塔旅人 · 更新未完成',
                0x80000000 | 0x80000, x, y, width, height, None, None, self.instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self.edit = self.u.CreateWindowExW(0, 'EDIT', self.text.replace('\r\n', '\n').replace('\n', '\r\n'),
                0x40000000 | 0x10000000 | 0x10000 | 0x200000 | 4 | 0x40 | 0x800,
                0, 0, 1, 1, hwnd, ctypes.c_void_p(102), self.instance, None)
            if not self.edit:
                raise ctypes.WinError(ctypes.get_last_error())
            self.u.SendMessageW(self.edit, 0x30, self.fonts[12], 0)
            for identifier, name in ((101, '打开日志目录'), (100, '复制详情'), (1, '关闭'), (2, '关闭窗口')):
                button = self.u.CreateWindowExW(0, 'BUTTON', name, 0x40000000 | 0x10000000 | 0x10000 | 0xB,
                    0, 0, 1, 1, hwnd, ctypes.c_void_p(identifier), self.instance, None)
                if not button:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.buttons[button] = identifier
                self.u.SendMessageW(button, 0x30, self.fonts[12], 0)
            self.layout(hwnd)
            try:
                dwm = ctypes.WinDLL('dwmapi')
                dwm.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]
                corner = ctypes.c_int(2)
                dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
            except OSError:
                pass
            self.u.ShowWindow(hwnd, 5)
            # The updater is launched with windowsHide/CREATE_NO_WINDOW. Windows
            # may apply STARTUPINFO(SW_HIDE) to the first ShowWindow call.
            self.u.ShowWindow(hwnd, 9)
            self.u.SetForegroundWindow(hwnd)
            self.u.UpdateWindow(hwnd)
            self.u.SetFocus(next(handle for handle, identifier in self.buttons.items() if identifier == 1))
            event = w.MSG()
            while True:
                status = self.u.GetMessageW(ctypes.byref(event), None, 0, 0)
                if status == 0:
                    break
                if status == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if event.message == 0x100 and event.wParam == 27:
                    self.u.DestroyWindow(hwnd)
                    continue
                if self.u.IsDialogMessageW(hwnd, ctypes.byref(event)):
                    continue
                self.u.TranslateMessage(ctypes.byref(event))
                self.u.DispatchMessageW(ctypes.byref(event))
            if self.callback_error:
                raise RuntimeError('故障窗口绘制失败') from self.callback_error
        finally:
            for obj in (*self.fonts.values(), *self.brushes.values()):
                self.g.DeleteObject(obj)
            self.u.UnregisterClassW(self.class_name, self.instance)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='星塔旅人故障详情窗口')
    parser.add_argument('--message', required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--settings', type=Path)
    args = parser.parse_args()
    show_failure(args.message, log_path=args.log, settings_path=args.settings)
