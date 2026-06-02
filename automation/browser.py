import os
import sys
import subprocess
import asyncio
from playwright.async_api import async_playwright

class BrowserManager:
    """
    Singleton manager for the Playwright automation engine.
    Self-contained, with self-healing browser installer and UI logging support.
    """
    _instance = None
    _playwright = None
    _browser = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BrowserManager, cls).__new__(cls)
        return cls._instance

    async def initialize(self, log_callback=None):
        """Initializes the Playwright driver engine."""
        if self._playwright is None:
            if log_callback:
                log_callback("[Browser] Starting Playwright engine...")
            self._playwright = await async_playwright().start()

    async def _ensure_browser(self, log_callback=None, interactive=True):
        """Ensures that a Chromium instance is active and connected. Installs if missing."""
        await self.initialize(log_callback)
        
        if self._browser is None or not self._browser.is_connected():
            headless = not interactive
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=headless,
                    args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
                )
            except Exception as e:
                err_str = str(e).lower()
                if "executable" in err_str or "not found" in err_str or "none" in err_str or "attribute" in err_str:
                    if log_callback:
                        log_callback("[Browser] Chromium binaries missing/invalid. Attempting self-healing install...")
                    
                    try:
                        # Clean up old state if corrupted
                        if self._playwright:
                            try:
                                await self._playwright.stop()
                            except Exception:
                                pass
                            self._playwright = None
                        
                        # Direct call to install chromium
                        # Running python -m playwright install chromium
                        proc = await asyncio.create_subprocess_exec(
                            sys.executable, "-m", "playwright", "install", "chromium",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE
                        )
                        
                        if log_callback:
                            log_callback("[Browser] Downloading and installing Chromium binaries. Please wait...")
                        
                        stdout, stderr = await proc.communicate()
                        
                        if proc.returncode == 0:
                            if log_callback:
                                log_callback("[Browser] Chromium binaries installed successfully.")
                        else:
                            raise RuntimeError(f"Playwright installation failed: {stderr.decode()}")
                        
                        # Re-initialize after install
                        await self.initialize(log_callback)
                        self._browser = await self._playwright.chromium.launch(
                            headless=headless,
                            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
                        )
                    except Exception as install_err:
                        if log_callback:
                            log_callback(f"[Error] Failed to auto-install browser binaries: {install_err}")
                        raise install_err
                else:
                    if log_callback:
                        log_callback(f"[Error] Failed to launch browser: {e}")
                    raise e

    async def get_context(self, log_callback=None, interactive=True):
        """
        Returns a fresh, isolated, and thread-safe browser context.
        Self-heals if the underlying browser was closed.
        """
        try:
            await self._ensure_browser(log_callback, interactive)
            return await self._browser.new_context(
                no_viewport=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                bypass_csp=True
            )
        except Exception as e:
            if log_callback:
                log_callback(f"[Browser] Error obtaining context ({e}). Resetting browser...")
            self._browser = None # Force reset
            await self._ensure_browser(log_callback, interactive)
            return await self._browser.new_context(
                no_viewport=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                bypass_csp=True
            )

    async def close(self):
        """Total cleanup for application shutdown."""
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
