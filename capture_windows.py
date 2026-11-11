"""Windows adapter for the application's user-started report collector.

Only the visible UAGame window is captured. No process memory is read.
All input is guarded by foreground-window, geometry and F8 checks.
"""
import ctypes as C
from ctypes import wintypes as W
import time
from dataclasses import dataclass
from pathlib import Path
from PIL import ImageGrab


class CaptureStopped(RuntimeError): pass
class CaptureError(RuntimeError): pass


@dataclass
class GameWindow:
    hwnd: int
    title: str
    path: str


def api():
    user = C.WinDLL('user32', use_last_error=True)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    user.GetForegroundWindow.restype = W.HWND
    user.GetAncestor.argtypes = [W.HWND, W.UINT]; user.GetAncestor.restype = W.HWND
    user.IsWindow.argtypes = [W.HWND]
    user.IsWindowVisible.argtypes = [W.HWND]
    user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.IsIconic.argtypes = [W.HWND]
    user.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    user.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
    user.SetForegroundWindow.argtypes = [W.HWND]
    user.ShowWindow.argtypes = [W.HWND, C.c_int]
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]; kernel.OpenProcess.restype = W.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    return user, kernel


def game_windows():
    user, kernel = api(); found = []
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def visit(hwnd, _):
        if not user.IsWindowVisible(hwnd): return True
        pid = W.DWORD(); user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if not handle: return True
        try:
            path = C.create_unicode_buffer(32768); size = W.DWORD(len(path))
            if kernel.QueryFullProcessImageNameW(handle, 0, path, C.byref(size)) and Path(path.value).name.lower() == 'uagame.exe':
                title = C.create_unicode_buffer(1024); user.GetWindowTextW(hwnd, title, len(title))
                found.append(GameWindow(int(hwnd), title.value, path.value))
        finally: kernel.CloseHandle(handle)
        return True
    callback = callback_type(visit)
    user.EnumWindows(callback, 0)
    return found


def viewport(size):
    """ABI renders a centered 16:9 viewport, including on this 4:3 screen."""
    w, h = size
    if w/h < 16/9:
        height = round(w*9/16); return (0, (h-height)//2, w, height)
    width = round(h*16/9); return ((w-width)//2, 0, width, h)


class Desktop:
    def __init__(self, window, stopped=lambda: False):
        self.window = window; self.stopped = stopped; self.user, _ = api(); self.geometry = None
        self.user.GetAsyncKeyState(0x77)  # Clear key presses from before this session.

    def check(self, foreground=True):
        if self.stopped() or self.user.GetAsyncKeyState(0x77) & 0x8001:
            raise CaptureStopped('已停止采集（F8 / 停止按钮）。已采集结果已保留。')
        hwnd = self.window.hwnd
        if not self.user.IsWindow(hwnd) or self.user.IsIconic(hwnd):
            raise CaptureStopped('游戏窗口已关闭或最小化，采集已停止。')
        if foreground and self.user.GetAncestor(self.user.GetForegroundWindow(), 2) != hwnd:
            raise CaptureStopped('前台窗口已改变，采集已停止；不会向其他窗口发送操作。')
        rect = W.RECT(); origin = W.POINT(0, 0)
        if not self.user.GetClientRect(hwnd, C.byref(rect)) or not self.user.ClientToScreen(hwnd, C.byref(origin)):
            raise CaptureError('无法读取游戏窗口范围。')
        bounds = (origin.x, origin.y, origin.x+rect.right, origin.y+rect.bottom)
        if self.geometry and bounds != self.geometry:
            raise CaptureStopped('游戏窗口位置或分辨率已变化，请重新开始采集。')
        if rect.right < 960 or rect.bottom < 540: raise CaptureError('游戏窗口过小，请至少使用 960×540。')
        return bounds

    def activate(self):
        if self.user.IsIconic(self.window.hwnd): self.user.ShowWindow(self.window.hwnd, 9)
        self.user.SetForegroundWindow(self.window.hwnd)
        time.sleep(.7)
        self.geometry = self.check()

    def wait(self, seconds):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            self.check(); time.sleep(.05)

    def screenshot(self):
        bounds = self.check()
        image = ImageGrab.grab(bbox=bounds, all_screens=True).convert('RGB')
        self.check()
        return image

    def move(self, x, y):
        bounds = self.check(); vx, vy, w, h = viewport((bounds[2]-bounds[0], bounds[3]-bounds[1]))
        self.user.SetCursorPos(round(bounds[0]+vx+x*w), round(bounds[1]+vy+y*h))

    def mouse_event(self, flags, data=0, guard=True):
        # Win32 INPUT must include keyboard/hardware union sizes on both architectures.
        class Mouse(C.Structure):
            _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]
        class Keyboard(C.Structure):
            _fields_ = [('vk', W.WORD), ('scan', W.WORD), ('flags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]
        class Hardware(C.Structure):
            _fields_ = [('msg', W.DWORD), ('paramL', W.WORD), ('paramH', W.WORD)]
        class Union(C.Union): _fields_ = [('mi', Mouse), ('ki', Keyboard), ('hi', Hardware)]
        class Input(C.Structure): _fields_ = [('type', W.DWORD), ('value', Union)]
        event = Input(0, Union(mi=Mouse(0, 0, data & 0xffffffff, flags, 0, 0)))
        if guard: self.check()
        if self.user.SendInput(1, C.byref(event), C.sizeof(event)) != 1:
            raise CaptureError('Windows 未接受鼠标操作；请保持游戏与本软件的运行权限一致。')

    def click(self, x, y):
        self.move(x, y); self.wait(.08); self.mouse_event(0x0002)
        try: time.sleep(.12)
        finally: self.mouse_event(0x0004, guard=False)
        self.check()

    def scroll(self, amount):
        self.move(.55, .55); self.wait(.08); self.mouse_event(0x0800, amount)
