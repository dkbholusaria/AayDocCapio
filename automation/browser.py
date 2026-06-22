import os
import sys
import subprocess
import asyncio
from playwright.async_api import async_playwright


def _get_system_proxy() -> dict | None:
    """
    Read Windows system proxy settings from the registry.
    Returns a Playwright-compatible proxy dict or None if no proxy is set.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        )
        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if not proxy_enable:
            return None
        proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
        winreg.CloseKey(key)
        if not proxy_server:
            return None
        # ProxyServer may be "host:port" or "http=host:port;https=host:port"
        if "=" in proxy_server:
            # Parse per-protocol format
            for part in proxy_server.split(";"):
                if part.startswith("https="):
                    proxy_server = part[6:]
                    break
                if part.startswith("http="):
                    proxy_server = part[5:]
        if not proxy_server.startswith("http"):
            proxy_server = "http://" + proxy_server
        return {"server": proxy_server}
    except Exception:
        return None


def _playwright_browsers_dir() -> str:
    """
    Stable directory for Playwright browser binaries.
    Always stored in AppData (~/Library/Application Support on macOS,
    ~/.local/share on Linux) so they survive app updates and are
    shared across runs.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, "AayDocCapio", "browsers")
    os.makedirs(path, exist_ok=True)
    return path


def _playwright_cli() -> str:
    """
    Path to the playwright CLI executable.
    When frozen by Nuitka/PyInstaller the bundled playwright package
    ships its own entry-point script; find it relative to the package.
    """
    if getattr(sys, "frozen", False):
        # Nuitka one-dir: playwright package is next to the exe
        exe_dir = os.path.dirname(sys.executable)
        for candidate in [
            os.path.join(exe_dir, "playwright", "__main__.py"),
            os.path.join(exe_dir, "_internal", "playwright", "__main__.py"),
        ]:
            if os.path.exists(candidate):
                return candidate
        # Last resort: let the OS find it
        return "playwright"
    else:
        # Running as script: use the same Python to invoke playwright module
        return None   # signals: use sys.executable -m playwright


async def _install_chromium(log_callback=None):
    """Download Chromium into the stable AppData browsers directory."""
    browsers_dir = _playwright_browsers_dir()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_dir

    if log_callback:
        log_callback("[Browser] Downloading Chromium — this only happens once, please wait...")

    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver_executable, driver_cli = compute_driver_executable()
        cmd = [driver_executable, driver_cli, "install", "chromium"]
        env = {**os.environ, **get_driver_env(), "PLAYWRIGHT_BROWSERS_PATH": browsers_dir}
    except Exception as e:
        # Fallback to system execution if playwright internals change
        if log_callback:
            log_callback(f"[Browser] Internals error: {e}, falling back to system execution...")
        cli = _playwright_cli()
        if cli is None or cli == "playwright":
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
        else:
            py = os.environ.get("PYTHONPATH_FOR_PLAYWRIGHT") or "python"
            cmd = [py, cli, "install", "chromium"]
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": browsers_dir}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"Chromium install failed (exit {proc.returncode}):\n{stderr.decode()[:500]}"
        )
    if log_callback:
        log_callback("[Browser] Chromium installed successfully.")


class BrowserManager:
    """
    Singleton Playwright browser manager with self-healing Chromium install.
    Stores browser binaries in AppData so they persist across app updates.
    """
    _instance = None
    _playwright = None
    _browser = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _set_browsers_env(self):
        """Tell Playwright where to find/store browsers before any API call."""
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _playwright_browsers_dir()

    async def initialize(self, log_callback=None):
        if self._playwright is None:
            self._set_browsers_env()
            if log_callback:
                log_callback("[Browser] Starting Playwright engine...")
            self._playwright = await async_playwright().start()

    # No --start-maximized: it fights the fixed 1600x900 viewport and distorts
    # the aspect ratio (collapsing the ITD nav). The competitor relies purely
    # on the viewport, letting the window auto-size to it.
    _LAUNCH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--password-store=basic",
        "--use-mock-keychain",
    ]
    _IGNORE_DEFAULT_ARGS = ["--enable-automation"]

    async def _launch(self, headless, log_callback=None):
        """
        Launch the browser. Prefer the user's installed Google Chrome
        (channel='chrome') — the Insight/AIS portal's download buttons only
        fire on real Chrome; bundled Chromium silently no-ops them.
        Fall back to bundled Chromium if Chrome is absent (26AS still works,
        but AIS/TIS downloads will fail — warn the user).
        Automatically picks up Windows system proxy from the registry.
        """
        proxy = _get_system_proxy()
        if proxy and log_callback:
            log_callback(f"[Browser] System proxy detected: {proxy['server']}")
        args = list(self._LAUNCH_ARGS)
        if headless:
            # Force modern headless mode and suppress any leaked window on ARM64
            args += [
                "--headless=new",
                "--disable-gpu",
                "--window-position=-10000,-10000",
            ]
        launch_kwargs = dict(
            headless=headless,
            args=args,
            ignore_default_args=self._IGNORE_DEFAULT_ARGS,
        )
        if proxy:
            launch_kwargs["proxy"] = proxy
        try:
            browser = await self._playwright.chromium.launch(
                channel="chrome", **launch_kwargs
            )
            self._channel = "chrome"
            return browser
        except Exception:
            if log_callback:
                log_callback(
                    "[Browser] WARNING: Google Chrome not found — using bundled Chromium. "
                    "26AS will work, but AIS/TIS downloads need Google Chrome installed "
                    "(https://www.google.com/chrome/)."
                )
            browser = await self._playwright.chromium.launch(**launch_kwargs)
            self._channel = "chromium"
            return browser

    async def _ensure_browser(self, log_callback=None, interactive=True):
        await self.initialize(log_callback)
        if self._browser is None or not self._browser.is_connected():
            headless = not interactive
            try:
                self._browser = await self._launch(headless, log_callback)
                if log_callback:
                    log_callback(f"[Browser] Launched via {getattr(self, '_channel', 'chromium')}")
            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ("executable", "not found", "doesn't exist", "none", "attribute")):
                    if log_callback:
                        log_callback("[Browser] Chromium not found — installing now...")
                    # Stop playwright before reinstalling
                    try:
                        if self._playwright:
                            await self._playwright.stop()
                            self._playwright = None
                    except Exception:
                        pass

                    await _install_chromium(log_callback)

                    # Re-init and retry
                    self._set_browsers_env()
                    await self.initialize(log_callback)
                    self._browser = await self._launch(headless, log_callback)
                else:
                    if log_callback:
                        log_callback(f"[Error] Failed to launch browser: {e}")
                    raise

    async def get_context(self, log_callback=None, interactive=True):
        try:
            await self._ensure_browser(log_callback, interactive)
        except Exception as e:
            if log_callback:
                log_callback(f"[Browser] Retrying after error: {e}")
            self._browser = None
            await self._ensure_browser(log_callback, interactive)

        # Match the competitor's working context exactly: fixed 1600x900 viewport,
        # no bypass_csp (real Chrome handles CSP fine and the portal expects it).
        _context_kwargs = dict(
            viewport={"width": 1600, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            accept_downloads=True,
        )
        try:
            ctx = await self._browser.new_context(**_context_kwargs)
        except Exception as e:
            # Browser object is stale (disconnected Chrome process) — force a full restart.
            if log_callback:
                log_callback(f"[Browser] Context creation failed ({e}), restarting browser...")
            self._browser = None
            self._playwright = None
            await self._ensure_browser(log_callback, interactive)
            ctx = await self._browser.new_context(**_context_kwargs)

        # Spoof automation-detection properties
        await ctx.add_init_script("""() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3, 4, 5] });
            window.chrome = window.chrome || { runtime: {} };
        }""")
        return ctx

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        finally:
            self._browser = None
            self._playwright = None


# Shared global instance
browser_manager = BrowserManager()
