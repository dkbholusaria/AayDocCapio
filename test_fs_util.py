"""Unit tests for automation/fs_util.py (F-14 / #14)."""
import os
import sys
import tempfile

from automation.fs_util import is_present, skip_missing_required


def test_missing_file_is_not_present():
    with tempfile.TemporaryDirectory() as d:
        assert is_present(os.path.join(d, "nope.pdf")) is False


def test_empty_file_is_not_present():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "empty.pdf")
        open(path, "wb").close()
        assert is_present(path) is False


def test_non_empty_file_is_present():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ok.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 test")
        assert is_present(path) is True


def test_directory_is_not_present():
    with tempfile.TemporaryDirectory() as d:
        assert is_present(d) is False


def test_skip_helper_only_skips_when_present():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ok.pdf")
        logs = []
        assert skip_missing_required(path, log=logs.append) is False
        assert logs == []
        with open(path, "wb") as f:
            f.write(b"data")
        assert skip_missing_required(path, log=logs.append) is True
        assert len(logs) == 1 and "[Skip]" in logs[0]


if __name__ == "__main__":
    import sys
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
