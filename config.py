import sys, os, subprocess, logging

_log = logging.getLogger(__name__)


def _app_dir() -> str:
    """
    Writable user-data directory for vault, settings, and outputs.
    - Windows compiled .exe : %LOCALAPPDATA%\\AayDocCapio
    - macOS compiled app    : ~/Library/Application Support/AayDocCapio
    - Linux/WSL compiled    : ~/.local/share/AayDocCapio
    - Running as script     : folder containing app.py
    """
    if getattr(sys, "frozen", False) or globals().get("__compiled__"):
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        elif sys.platform == "darwin":
            base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
        else:
            base = os.path.join(os.path.expanduser("~"), ".local", "share")
        data_dir = os.path.join(base, "AayDocCapio")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    return os.path.dirname(os.path.abspath(__file__))


def _log_open(msg: str):
    """Write open-folder diagnostics to a separate file to avoid Windows file-lock conflict with the main logging.FileHandler."""
    try:
        from datetime import datetime
        log_path = os.path.join(_app_dir(), "open_folder.log")
        line = f"[{datetime.now().strftime('%d-%m-%Y %H:%M:%S')}] {msg}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _default_download_dir() -> str:
    """
    Sensible default output directory per platform.
    - Windows (native or WSL): %USERPROFILE%\\Downloads → Documents → USERPROFILE
    - macOS  : ~/Downloads  (always exists on Mac)
    - Linux  : ~/Downloads if it exists, otherwise ~  (never create it)

    USERPROFILE takes priority over sys.platform so that WSL dev runs
    (sys.platform == 'linux' but USERPROFILE points to a real Windows path
    like C:\\Users\\deepak) pick the Windows Downloads folder correctly.
    Never creates the folder — just returns the path.
    """
    userprofile = os.environ.get("USERPROFILE", "")
    if userprofile and os.path.isdir(userprofile):
        downloads = os.path.join(userprofile, "Downloads")
        if os.path.isdir(downloads):
            return downloads
        documents = os.path.join(userprofile, "Documents")
        if os.path.isdir(documents):
            return documents
        return userprofile

    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Downloads")
    downloads = os.path.join(home, "Downloads")
    return downloads if os.path.isdir(downloads) else home


def _bundled_dir() -> str:
    """
    Directory for read-only assets bundled inside the .exe.
    PyInstaller uses _MEIPASS; Nuitka uses the exe directory.
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    if globals().get("__compiled__"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _is_reparse_point(path: str) -> bool:
    """Return True if path is a junction or symlink (reparse point) on Windows."""
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        result = bool(attrs != 0xFFFFFFFF and attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        _log_open(f"[OpenFolder] _is_reparse_point({path!r}) attrs={attrs:#010x} result={result}")
        return result
    except Exception as e:
        _log_open(f"[OpenFolder] _is_reparse_point error: {e}")
        return False


def _resolve_win_path(path: str) -> str:
    """
    Resolve the real filesystem path for Explorer to open without errors.
    - SUBST drives: parse 'subst' output to find the real root
    - Junctions / symlinks: use os.path.realpath() — Explorer raises
      "untrusted mount point" when asked to traverse reparse points directly
    - Everything else: return as-is
    """
    import re
    win_path = path.replace("/", "\\")

    # Check for junction / symlink first — Explorer can't traverse them
    if _is_reparse_point(win_path):
        real = os.path.realpath(win_path)
        _log_open(f"[OpenFolder] Reparse point resolved: {win_path} → {real}")
        return real

    drive = os.path.splitdrive(win_path)[0].upper()
    if not drive:
        return win_path
    drive_slash = drive + "\\"
    try:
        out = subprocess.check_output(["subst"], text=True, timeout=3,
                                      creationflags=0x08000000)  # CREATE_NO_WINDOW
        _log_open(f"[OpenFolder] subst output: {out.strip()!r}")
        for line in out.splitlines():
            # subst output format: "D:\: => C:\Real\Path"
            m = re.match(r"([A-Z]:\\):\s*=>\s*(.+)", line)
            if m and m.group(1).upper() == drive_slash.upper():
                real_root = m.group(2).rstrip("\\")
                rel = os.path.relpath(win_path, drive_slash)
                resolved = os.path.join(real_root, rel) if rel != "." else real_root
                _log_open(f"[OpenFolder] SUBST resolved: {win_path} → {resolved}")
                return resolved
    except Exception as e:
        _log_open(f"[OpenFolder] subst command failed: {e}")
    _log_open(f"[OpenFolder] No mapping found, using path as-is: {win_path}")
    return win_path


def _open_path(path: str):
    """Open a file or folder in the OS file manager / default app."""
    if not path:
        return
    _log_open(f"[OpenFolder] Requested: {path!r}  exists={os.path.exists(path)}")
    if not os.path.exists(path):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(None, "Folder Not Found",
            f"The folder has not been created yet:\n{path}\n\n"
            "It will be created when the first file is downloaded.")
        return
    try:
        if sys.platform == "win32":
            # Try 1: cmd /c start with shell=True — Windows shell resolves
            # SUBST/mapped drives natively; works from both script and .exe
            try:
                resolved = _resolve_win_path(path)
                _log_open(f"[OpenFolder] Trying cmd /c start with: {resolved!r}")
                subprocess.Popen(
                    f'cmd /c start "" "{resolved}"',
                    shell=True, creationflags=0x08000000)
                _log_open(f"[OpenFolder] cmd /c start launched OK")
                return
            except Exception as e:
                _log_open(f"[OpenFolder] cmd /c start failed: {e}")

            # Try 2: full path to explorer.exe
            try:
                explorer = os.path.join(
                    os.environ.get("WINDIR", "C:\\Windows"), "explorer.exe")
                win_path = path.replace("/", "\\")
                _log_open(f"[OpenFolder] Trying explorer at: {explorer!r} path: {win_path!r}")
                subprocess.Popen([explorer, win_path])
                _log_open(f"[OpenFolder] explorer.exe launched OK")
                return
            except Exception as e:
                _log_open(f"[OpenFolder] explorer.exe failed: {e}")

            # Try 3: os.startfile fallback
            _log_open(f"[OpenFolder] Falling back to os.startfile: {path!r}")
            os.startfile(path)

        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            wsl_exe = "/mnt/c/Windows/explorer.exe"
            if os.path.exists(wsl_exe):
                wsl_path = subprocess.run(
                    ["wslpath", "-w", path], capture_output=True, text=True).stdout.strip()
                subprocess.Popen([wsl_exe, wsl_path or path])
            else:
                subprocess.Popen(["xdg-open", path])
    except Exception as e:
        _log_open(f"[OpenFolder] All attempts failed for {path!r}: {e}")
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(None, "Could Not Open Folder",
            f"Failed to open folder in file manager:\n{path}\n\nError: {e}")
