def _friendly_error(raw: str) -> str:
    """
    Translate technical Playwright / network exception messages into plain
    English suitable for display in the progress table status column.
    """
    r = raw.lower()
    if "account locked" in r:
        return "Account locked — client must unlock via ITD portal (incometax.gov.in) before retrying."
    if "authentication failed" in r:
        for prefix in ("authentication failed: ", "authentication failed"):
            if raw.lower().startswith(prefix):
                return raw[len(prefix):].strip() or "Incorrect credentials"
        return raw
    if "scheduled maintenance" in r or "under scheduled maintenance" in r:
        return raw
    if "err_empty_response" in r or "empty response" in r:
        return "ITD portal is not responding — portal may be down for maintenance. Open incometax.gov.in in a browser to check, then retry."
    if "err_connection_refused" in r or "connection refused" in r:
        return "ITD portal refused the connection — it may be down for maintenance. Try again in a few minutes."
    if "err_name_not_resolved" in r or "name not resolved" in r:
        return "Cannot reach ITD portal — check your internet connection and try again."
    if "err_timed_out" in r or "timed out" in r or "timeout" in r:
        return "ITD portal took too long to respond — portal may be busy. Try again in a few minutes."
    if "err_connection_reset" in r or "connection reset" in r:
        return "Connection was reset by the portal — try again in a few minutes."
    if "net::" in r:
        import re as _re
        m = _re.search(r"net::(\w+)", raw)
        code = m.group(1) if m else "NETWORK_ERROR"
        return f"Network error — ITD portal may be temporarily unavailable. ({code})"
    if "target closed" in r or "browser has been closed" in r:
        return "Browser closed unexpectedly — try again"
    if "aborted by user" in r or "cancelled" in r:
        return "Stopped by user"
    if "2fa" in r or "otp" in r:
        return raw
    clean = raw.split("\n")[0].strip()
    if len(clean) > 72:
        clean = clean[:69] + "..."
    return clean
