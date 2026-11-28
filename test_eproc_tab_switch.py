import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.downloader_e_proceedings import (
    _activate_eproc_tab,
    _close_blocking_overlays,
)


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    async def click(self, timeout=None):
        self.page.click_calls.append(self.selector)
        if len(self.page.click_calls) <= self.page.fail_clicks:
            raise RuntimeError("modal intercepts pointer events")

    async def get_attribute(self, name):
        return "true" if not self.page.fail_clicks else "false"


class FakePage:
    def __init__(self, fail_clicks=0, js_click_ok=True):
        self.fail_clicks = fail_clicks
        self.js_click_ok = js_click_ok
        self.click_calls = []
        self.evaluated = []

    def locator(self, selector):
        return FakeLocator(self, selector)

    async def evaluate(self, script, arg=None):
        self.evaluated.append((script, arg))
        if "mat-mdc-tab" in script:
            return self.js_click_ok
        return None


def _step(_msg):
    pass


def test_tab_click_retries_after_clearing_overlays():
    page = FakePage(fail_clicks=2)
    ok = asyncio.run(_activate_eproc_tab(page, "For your Information", _step))
    assert ok is True
    assert len(page.click_calls) == 3
    cleanup = [s for s, _ in page.evaluated if ".modal.show" in s]
    assert len(cleanup) >= 3
    assert not [s for s, _ in page.evaluated if "mat-mdc-tab" in s]


def test_tab_click_falls_back_to_javascript():
    page = FakePage(fail_clicks=10, js_click_ok=True)
    ok = asyncio.run(_activate_eproc_tab(page, "For your Information", _step))
    assert ok is True
    js = [(s, a) for s, a in page.evaluated if "mat-mdc-tab" in s]
    assert js and js[-1][1] == "For your Information"


def test_tab_falls_back_to_false_when_javascript_click_fails():
    page = FakePage(fail_clicks=10, js_click_ok=False)
    ok = asyncio.run(_activate_eproc_tab(page, "For your Information", _step))
    assert ok is False


def test_close_blocking_overlays_removes_backdrops():
    page = FakePage()
    asyncio.run(_close_blocking_overlays(page))
    scripts = [s for s, _ in page.evaluated]
    assert any(".modal-backdrop" in s for s in scripts)
    assert any(".cdk-overlay-backdrop-showing" in s for s in scripts)
