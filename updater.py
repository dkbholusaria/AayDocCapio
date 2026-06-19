import threading
import urllib.request
import json
from version import __version__

_REPO = "dkbholusaria/AayDocCapio"
_API  = f"https://api.github.com/repos/{_REPO}/releases/latest"


def check_for_update(callback):
    """Check GitHub for a newer release in a background thread.

    Calls callback(tag, release_url) if a newer version exists,
    or callback(None, None) if up to date or on any error.
    """
    def _run():
        try:
            req = urllib.request.Request(
                _API,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "AayDocCapio",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            tag = data.get("tag_name", "").lstrip("v")
            release_url = data.get(
                "html_url",
                f"https://github.com/{_REPO}/releases/latest",
            )
            if _newer(tag, __version__):
                callback(tag, release_url)
            else:
                callback(None, None)
        except Exception:
            callback(None, None)

    threading.Thread(target=_run, daemon=True).start()


def _newer(a: str, b: str) -> bool:
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except ValueError:
        return False
