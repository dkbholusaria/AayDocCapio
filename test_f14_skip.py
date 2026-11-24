"""F-14 (#14) — skip-already-downloaded guards.

Covers the entry points that check the local file BEFORE touching Playwright,
so they can be exercised with a dummy `page`/`portal` of None.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.fs_util import is_present
from automation.downloader_ais_tis import (
    download_tis,
    request_ais,
    download_ais_from_activity_history,
    run_request_ais,
)
from automation.downloader_26as import download_26as
from automation.downloader_168 import download_168
from automation.downloader_filed_returns import _download_one_file


def _touch(path, data=b"test"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _noop(_msg):
    pass


def test_tis_skip_when_present():
    with tempfile.TemporaryDirectory() as d:
        _touch(os.path.join(d, "AIS-TIS", "AAAAA0000A-TIS-2024_25.pdf"))
        out = asyncio.run(download_tis(None, "2024-25", d, _noop, pan="AAAAA0000A"))
        assert out["status"] == "already_present", out


def test_ais_request_skip_when_present():
    with tempfile.TemporaryDirectory() as d:
        _touch(os.path.join(d, "AIS-TIS", "AAAAA0000A-AIS-2024_25.pdf"))
        out = asyncio.run(request_ais(None, "2024-25", d, _noop, pan="AAAAA0000A"))
        assert out["status"] == "already_present", out


def test_ais_activity_history_skip_when_present():
    with tempfile.TemporaryDirectory() as d:
        _touch(os.path.join(d, "AIS-TIS", "AAAAA0000A-AIS-2024_25.pdf"))
        out = asyncio.run(
            download_ais_from_activity_history(None, "2024-25", d, _noop, pan="AAAAA0000A"))
        assert out["status"] == "already_present", out


def test_ais_does_not_skip_when_missing():
    # With no file present the guard must fall through and try the portal —
    # None blows up inside, which proves the guard did not short-circuit.
    with tempfile.TemporaryDirectory() as d:
        try:
            asyncio.run(download_tis(None, "2024-25", d, _noop, pan="AAAAA0000A"))
        except Exception:
            return
        raise AssertionError("expected portal interaction when file is absent")


def test_filed_return_artifact_skip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ITR-2024_25-Original-Form.pdf")
        _touch(path)
        status = asyncio.run(
            _download_one_file(None, None, path, _noop, "ITR Form"))
        assert status == "already_present", status
        assert is_present(path)


def test_26as_existing_year_skips_traces_navigation():
    with tempfile.TemporaryDirectory() as d:
        sub = os.path.join(d, "26AS")
        _touch(os.path.join(sub, "AAAAA0000A-26AS-2024_25.pdf"))
        _touch(os.path.join(sub, "AAAAA0000A-26AS-2024_25.txt"))
        res = asyncio.run(download_26as(
            None, ["2024-25"], lambda ay: d, _noop, pan="AAAAA0000A"))
        ok, msg, txt = res["2024-25"]
        assert ok and msg.startswith("Already present"), res
        assert txt.endswith("26AS-2024_25.txt")


def test_168_existing_year_skips_traces2_navigation():
    with tempfile.TemporaryDirectory() as d:
        sub = os.path.join(d, "168")
        _touch(os.path.join(sub, "AAAAA0000A-168-2026_27.pdf"))
        _touch(os.path.join(sub, "AAAAA0000A-168-2026_27-itd.xlsx"))
        _touch(os.path.join(sub, "AAAAA0000A-168-2026_27.txt"))
        res = asyncio.run(download_168(
            None, ["2026-27"], lambda ty: d, _noop, pan="AAAAA0000A"))
        ok, msg, txt = res["2026-27"]
        assert ok and msg.startswith("Already present"), res


def test_ais_request_phase_all_present_skips_portal():
    with tempfile.TemporaryDirectory() as d:
        sub = os.path.join(d, "AIS-TIS")
        _touch(os.path.join(sub, "AAAAA0000A-AIS-2024_25.pdf"))
        _touch(os.path.join(sub, "AAAAA0000A-TIS-2024_25.pdf"))
        res = asyncio.run(run_request_ais(
            None, ["2024-25"], lambda fy: d, _noop, pan="AAAAA0000A"))
        out = res["2024-25"]
        assert out["status"] == "already_present", out
        assert out["tis"]["status"] == "already_present", out


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
