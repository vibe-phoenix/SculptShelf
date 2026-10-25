"""SculptShelf bridge plugin for ZBrush 2027 (ZBrush Python SDK, CPython 3.11).

Adds  ZPlugin > SculptShelf > Open SculptShelf  and receives load requests from the SculptShelf
companion application (SculptShelfData/App/SculptShelf.exe).

How requests arrive
-------------------
At startup this script registers a hidden Win32 *message-only* window on ZBrush's main thread.
SculptShelf.exe finds that window by class name and delivers each request as WM_COPYDATA through
SendMessageTimeout. Windows dispatches the message from ZBrush's own message loop, so every ZBrush
command below runs on ZBrush's main thread, only when a request is sent: there is no timer, no
polling, no simulated keyboard or mouse input and no background thread touching ZBrush.

The window procedure returns an integer result code (the acknowledgement) and writes a short JSON
detail message to the result file named in the request.

Loading uses the documented SDK pattern: zbrush.commands.set_next_filename(path) followed by
pressing "Brush:Load Brush", "Alpha:Import" or "Material:Load". Loading a brush, alpha or material does not touch the current
tool, subtools or project.
"""

import ctypes
import ctypes.wintypes as wt
import collections
import json
import os
import subprocess
import sys
import time
import traceback
import types

from zbrush import commands as zbc

VERSION = "1.3.0"
PROTOCOL = 1

MENU = "ZPlugin:SculptShelf"
OPEN_BUTTON = MENU + ":Open SculptShelf"

# The class name can be overridden only for the automated tests (never set in normal use).
WINDOW_CLASS = os.environ.get("SCULPTSHELF_BRIDGE_CLASS") or "SculptShelf.ZBridge.v1"
COPYDATA_MAGIC = 0x53534C46  # 'SSLF'
SHOW_EVENT_NAME = "Local\\SculptShelf.ShowRequest"

RESULT_OK = 1
RESULT_DUPLICATE = 2
ERR_BAD_REQUEST = -2
ERR_MISSING_FILE = -3
ERR_UNSUPPORTED = -4
ERR_BUSY = -5
ERR_LOAD_FAILED = -6
ERR_PROTOCOL = -7

BRUSH_EXTENSIONS = {".zbp"}
ALPHA_EXTENSIONS = {".psd", ".bmp", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MATERIAL_EXTENSIONS = {".zmt"}

# ZBrush executes every *.py in its plugin folders, and the interpreter is shared and persistent.
# Objects that Windows calls back into (the window procedure) must outlive this script's namespace,
# so they are kept on a dedicated module registered in sys.modules.
_STATE_MODULE = "_sculptshelf_bridge_state"


def _state():
    mod = sys.modules.get(_STATE_MODULE)
    if mod is not None and not hasattr(mod, "loaded"):
        mod.loaded = {}
    if mod is not None and not hasattr(mod, "loaded_brushes"):
        mod.loaded_brushes = set()
    if mod is None:
        mod = types.ModuleType(_STATE_MODULE)
        mod.hwnd = None
        mod.wndproc = None
        mod.handler = None
        mod.busy = False
        mod.recent = collections.OrderedDict()
        mod.loaded = {}  # alphas and materials: normalized file path -> {"item": palette item path, "signature": (size, mtime)}
        mod.loaded_brushes = set()  # brush files loaded in this session (a reload makes ZBrush ask to reset)
        mod.plugin_dir = None
        sys.modules[_STATE_MODULE] = mod
    return mod


# --------------------------------------------------------------------------------------------------
# Logging (Documents\ZBrush\SculptShelf\Logs\bridge.log)
# --------------------------------------------------------------------------------------------------

def _local_root():
    home = os.environ.get("SCULPTSHELF_HOME")
    if home:
        return os.path.join(home, "Local")
    # Documents\ZBrush\SculptShelf (same folder as SculptShelf's settings; Documents may be redirected, e.g. OneDrive).
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
        docs = buf.value
    else:
        docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs, "ZBrush", "SculptShelf")


_LOG_FILE = os.path.join(_local_root(), "Logs", "bridge.log")


def _log(message):
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        if os.path.exists(_LOG_FILE) and os.path.getsize(_LOG_FILE) > 1024 * 1024:
            os.replace(_LOG_FILE, _LOG_FILE + ".1")
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


# --------------------------------------------------------------------------------------------------
# Win32 declarations
# --------------------------------------------------------------------------------------------------

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
HWND_MESSAGE = wt.HWND(-3)
WM_COPYDATA = 0x004A
ASFW_ANY = 0xFFFFFFFF
EVENT_MODIFY_STATE = 0x0002


class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wt.DWORD), ("lpData", ctypes.c_void_p)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
_user32.RegisterClassExW.restype = wt.ATOM
_user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
_user32.CreateWindowExW.restype = wt.HWND
_user32.IsWindow.argtypes = [wt.HWND]
_user32.IsWindow.restype = wt.BOOL
_user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
_user32.FindWindowExW.restype = wt.HWND
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_user32.GetWindowThreadProcessId.restype = wt.DWORD
_user32.AllowSetForegroundWindow.argtypes = [wt.DWORD]
_user32.AllowSetForegroundWindow.restype = wt.BOOL
_kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wt.HMODULE
_kernel32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_kernel32.OpenEventW.restype = wt.HANDLE
_kernel32.SetEvent.argtypes = [wt.HANDLE]
_kernel32.SetEvent.restype = wt.BOOL
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_kernel32.CloseHandle.restype = wt.BOOL
_kernel32.GetCurrentProcessId.restype = wt.DWORD


# --------------------------------------------------------------------------------------------------
# Request handling (runs on ZBrush's main thread, inside the window procedure)
# --------------------------------------------------------------------------------------------------

def _write_result(request, message, code):
    path = request.get("resultFile") if isinstance(request, dict) else None
    if not isinstance(path, str) or not path.lower().endswith(".json"):
        return
    # Only write into a SculptShelf "Bridge" folder.
    if os.path.basename(os.path.dirname(path)).lower() != "bridge":
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"id": request.get("id"), "code": code, "message": message}, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        _log(f"could not write result file {path}: {exc}")


def _load_asset(kind, path):
    """Loads one brush, alpha or material. Returns (code, message)."""
    ext = os.path.splitext(path)[1].lower()
    if kind == "brush":
        if ext not in BRUSH_EXTENSIONS:
            return ERR_UNSUPPORTED, f"Unsupported brush file type '{ext}': {path}"
        button = "Brush:Load Brush"
    elif kind == "alpha":
        if ext not in ALPHA_EXTENSIONS:
            return ERR_UNSUPPORTED, f"Unsupported alpha file type '{ext}': {path}"
        button = "Alpha:Import"
    elif kind == "material":
        if ext not in MATERIAL_EXTENSIONS:
            return ERR_UNSUPPORTED, f"Unsupported material file type '{ext}': {path}"
        button = "Material:Load"
    else:
        return ERR_BAD_REQUEST, f"Unknown asset kind '{kind}'."

    if not os.path.isfile(path):
        return ERR_MISSING_FILE, f"File not found: {path}"
    try:
        with open(path, "rb") as fh:
            fh.read(1)
    except OSError as exc:
        return ERR_MISSING_FILE, f"File cannot be read ({exc.strerror}): {path}"

    if not zbc.exists(button):
        return ERR_LOAD_FAILED, f"ZBrush interface item '{button}' was not found."

    # Brushes are always loaded from the file, so the brush comes back exactly as saved (its own alpha,
    # texture and settings), even if it was changed after an earlier load in this session.
    # Alphas and materials have nothing to reset: one already loaded in this session (and unchanged on disk)
    # is selected instead of loading it again.
    st = _state()
    key = os.path.normcase(os.path.abspath(path))
    try:
        info = os.stat(path)
        signature = (info.st_size, int(info.st_mtime))
    except OSError:
        signature = None
    name = os.path.splitext(os.path.basename(path))[0]
    switchable = kind in ("alpha", "material")
    known = st.loaded.get(key) if switchable else None
    if known and known["signature"] == signature and zbc.exists(known["item"]):
        zbc.press(known["item"])
        return RESULT_OK, f"Switched to {kind} '{name}' (already loaded)."

    # The palette item ZBrush is expected to create for this file. Only remembered when that name did not exist
    # before the load, so an unrelated brush/alpha (or button) with the same name is never pressed by mistake.
    candidate = {"brush": "Brush:", "alpha": "Alpha:", "material": "Material:"}[kind] + name
    existed_before = zbc.exists(candidate)

    def do_load():
        zbc.set_next_filename(path)
        zbc.press(button)

    # Reloading a brush that is already in ZBrush makes ZBrush ask "This brush is already loaded. Do you want to
    # reset the existing brush with the state on disk?" (YES / NO / Always YES). Resetting from disk is exactly
    # what SculptShelf wants, so the load runs while answering YES, the same way Maxon's SDK example answers a
    # document question with press_key("N", ...). The key only answers a note that appears during the load.
    reloading = kind == "brush" and (existed_before or key in st.loaded_brushes)
    answered = False
    if reloading:
        try:
            zbc.press_key("Y", do_load)
            answered = True
        except Exception as exc:
            _log(f"press_key could not answer the reload note ({exc}); loading normally")
    if not answered:
        do_load()
    if kind == "brush":
        st.loaded_brushes.add(key)

    if switchable and not existed_before and zbc.exists(candidate):
        st.loaded[key] = {"item": candidate, "signature": signature}

    # ZBrush records the file it last used; log a mismatch for diagnostics.
    try:
        used = zbc.get_last_used_filename() or ""
    except Exception:
        used = ""
    if os.path.normcase(os.path.abspath(used or ".")) != os.path.normcase(os.path.abspath(path)):
        _log(f"note: last used filename after load is '{used}', requested '{path}'")

    if reloading:
        return RESULT_OK, f"Reloaded brush '{name}' from disk."
    return RESULT_OK, f"Loaded {kind} '{name}'."


def _handle_request(raw):
    st = _state()
    try:
        request = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        _log(f"bad request payload: {exc}")
        return ERR_BAD_REQUEST
    if not isinstance(request, dict):
        return ERR_BAD_REQUEST

    if request.get("protocol") != PROTOCOL:
        _write_result(request, f"Protocol mismatch: SculptShelf app uses {request.get('protocol')}, plugin uses {PROTOCOL}. "
                               "Reinstall SculptShelf so both parts match.", ERR_PROTOCOL)
        return ERR_PROTOCOL

    req_id = request.get("id")
    if isinstance(req_id, str) and req_id in st.recent:
        return RESULT_DUPLICATE

    action = request.get("action")
    if action == "ping":
        _write_result(request, f"SculptShelf bridge {VERSION}, ZBrush {_zbrush_version()}", RESULT_OK)
        return RESULT_OK

    if action != "load":
        _write_result(request, f"Unknown action '{action}'.", ERR_BAD_REQUEST)
        return ERR_BAD_REQUEST

    if st.busy:
        _write_result(request, "ZBrush is still loading the previous asset.", ERR_BUSY)
        return ERR_BUSY

    kind = request.get("kind")
    path = request.get("path")
    if not isinstance(path, str) or not path:
        _write_result(request, "Request has no file path.", ERR_BAD_REQUEST)
        return ERR_BAD_REQUEST

    st.busy = True
    started = time.perf_counter()
    try:
        code, message = _load_asset(kind, path)
    except Exception as exc:
        _log(f"load failed for {path}:\n{traceback.format_exc()}")
        code, message = ERR_LOAD_FAILED, f"ZBrush could not load {path}: {exc}"
    finally:
        st.busy = False

    if isinstance(req_id, str):
        st.recent[req_id] = code
        while len(st.recent) > 64:
            st.recent.popitem(last=False)

    _log(f"load {kind} -> {code} in {(time.perf_counter() - started) * 1000:.0f} ms: {path}")
    _write_result(request, message, code)
    return code


def _wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_COPYDATA:
        try:
            cds = ctypes.cast(lparam, ctypes.POINTER(COPYDATASTRUCT)).contents
            if cds.dwData != COPYDATA_MAGIC or not cds.lpData or cds.cbData > 1024 * 1024:
                return 0
            raw = ctypes.string_at(cds.lpData, cds.cbData)
            return _handle_request(raw)
        except Exception:
            _log("unhandled error in request handler:\n" + traceback.format_exc())
            return ERR_LOAD_FAILED
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _zbrush_version():
    try:
        return f"{zbc.zbrush_info(0):g}"
    except Exception:
        return "?"


def _create_bridge_window():
    st = _state()
    if st.hwnd and _user32.IsWindow(st.hwnd):
        return True

    existing = _user32.FindWindowExW(HWND_MESSAGE, None, WINDOW_CLASS, None)
    if existing:
        pid = wt.DWORD(0)
        _user32.GetWindowThreadProcessId(existing, ctypes.byref(pid))
        if pid.value != _kernel32.GetCurrentProcessId():
            _log("another ZBrush instance already hosts the SculptShelf bridge; requests go to that instance")
            return False

    hinst = _kernel32.GetModuleHandleW(None)
    st.wndproc = WNDPROC(_wndproc)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = st.wndproc
    wc.hInstance = hinst
    wc.lpszClassName = WINDOW_CLASS
    atom = _user32.RegisterClassExW(ctypes.byref(wc))
    if not atom:
        err = ctypes.get_last_error()
        if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            _log(f"RegisterClassExW failed: {err}")
            return False
    st.wndclass = wc
    hwnd = _user32.CreateWindowExW(0, WINDOW_CLASS, "SculptShelf Bridge", 0, 0, 0, 0, 0,
                                   HWND_MESSAGE, None, hinst, None)
    if not hwnd:
        _log(f"CreateWindowExW failed: {ctypes.get_last_error()}")
        return False
    st.hwnd = hwnd
    _log(f"bridge window created (hwnd={hwnd:#x}, pid={_kernel32.GetCurrentProcessId()})")
    return True


# --------------------------------------------------------------------------------------------------
# Open SculptShelf
# --------------------------------------------------------------------------------------------------

def _app_path():
    plugin_dir = _state().plugin_dir or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(plugin_dir, "SculptShelfData", "App", "SculptShelf.exe")


def _open_sculptshelf(sender=None):
    try:
        # Let the companion take the foreground (ZBrush is the foreground app while its button is clicked).
        _user32.AllowSetForegroundWindow(ASFW_ANY)

        # An instance is already running: ask it to show and focus its window.
        handle = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
        if handle:
            try:
                _kernel32.SetEvent(handle)
            finally:
                _kernel32.CloseHandle(handle)
            return

        exe = _app_path()
        if not os.path.isfile(exe):
            zbc.message_ok(f"SculptShelf.exe was not found at:\n{exe}\n\nPlease reinstall SculptShelf.", "SculptShelf")
            return
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
        subprocess.Popen([exe, "--from-zbrush", str(_kernel32.GetCurrentProcessId())],
                         cwd=os.path.dirname(exe), close_fds=True, creationflags=flags)
        _log(f"launched {exe}")
    except Exception as exc:
        _log("open failed:\n" + traceback.format_exc())
        zbc.message_ok(f"SculptShelf could not be started:\n{exc}", "SculptShelf")


def _setup():
    st = _state()
    st.plugin_dir = os.path.dirname(os.path.abspath(__file__))
    _log(f"SculptShelf bridge {VERSION} starting in ZBrush {_zbrush_version()} (Python {sys.version.split()[0]}) from {st.plugin_dir}")

    if not zbc.exists(MENU):
        zbc.add_subpalette(MENU, 0)
    if not zbc.exists(OPEN_BUTTON):
        zbc.add_button(OPEN_BUTTON, "Open the SculptShelf brush, alpha and material browser.", _open_sculptshelf, False, 1.0)

    _create_bridge_window()


try:
    _setup()
except Exception:
    _log("SculptShelf bridge failed to initialise:\n" + traceback.format_exc())
    raise
