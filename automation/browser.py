import os
import sys
import subprocess
import asyncio
from playwright.async_api import async_playwright


def _playwright_browsers_dir() -> str:
    """
    Stable directory for Playwright browser binaries.
    Always stored in AppData (or ~/.local/share on Linux) so they
    survive app updates and are shared across runs.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, "ITDDocsDownloader", "browsers")
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

    cli = _playwright_cli()
    if cli is None or cli == "playwright":
        # Normal Python environment
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    else:
        # Frozen: run the bundled __main__.py with the system Python
        # Find system python
        py = os.environ.get("PYTHONPATH_FOR_PLAYWRIGHT") or "python"
        cmd = [py, cli, "install", "chromium"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": browsers_dir}
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

    async def _ensure_browser(self, log_callback=None, interactive=True):
        await self.initialize(log_callback)
        if self._browser is None or not self._browser.is_connected():
            headless = not interactive
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=headless,
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--password-store=basic",
                    ],
                    ignore_default_args=["--enable-automation"],
                )
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
                    self._browser = await self._playwright.chromium.launch(
                        headless=headless,
                        args=[
                            "--start-maximized",
                            "--disable-blink-features=AutomationControlled",
                            "--disable-features=IsolateOrigins,site-per-process",
                            "--password-store=basic",
                        ],
                        ignore_default_args=["--enable-automation"],
                    )
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

        ctx = await self._browser.new_context(
            no_viewport=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            bypass_csp=True,
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            accept_downloads=True,
        )
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
