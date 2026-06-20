import os
import re
import glob
import html
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ── Email activity log ────────────────────────────────────────────────────────
# Logs to <app_dir>/email_log.txt — every SMTP attempt with full server dialogue.

def _email_log_path() -> str:
    from config import _app_dir
    return os.path.join(_app_dir(), "email_log.txt")

def _log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        with open(_email_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def _divider(label: str):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"\n{'─' * 20}  {label}  {'─' * 20}  [{ts}]\n"
    try:
        with open(_email_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

def log_session_start():
    _divider("SESSION STARTED")

def log_session_end():
    _divider("SESSION ENDED")

# Regex to extract PAN from folder names like "ABCDE1234F-Client Name"
_PAN_RE = re.compile(r'^([A-Z]{5}[0-9]{4}[A-Z])-')

# Maps AY label → AY folder name prefix, e.g.:
#   "AY 2024-25 (FY 2023-24)" → "AY_2024_25"
#   "TY 2025-26 (FY 2025-26)" → "TY_2025_26"
def _ay_label_to_folder(ay_label: str) -> str:
    m = re.match(r'^(AY|TY)\s+(\d{4}-\d{2})', ay_label.strip())
    if not m:
        return ""
    kind = m.group(1)          # "AY" or "TY"
    year = m.group(2)          # "2024-25"
    year_safe = year.replace("-", "_")
    return f"{kind}_{year_safe}"


def scan_for_clients(root_dir: str, ay_label: str, vault_assessees: list) -> list:
    """
    Walk immediate sub-folders of root_dir for pattern {PAN}-*.
    For each PAN found, look for an AY sub-folder matching ay_label.
    Match PAN against vault_assessees.
    Returns list of dicts:
      {pan, name, email, cc, ay_folder_path, attachments}
    Only clients present in the vault are returned.
    """
    if not root_dir or not os.path.isdir(root_dir):
        return []

    ay_folder_name = _ay_label_to_folder(ay_label)
    vault_map = {a["pan"]: a for a in vault_assessees}

    results = []
    try:
        entries = os.listdir(root_dir)
    except PermissionError:
        return []

    for entry in sorted(entries):
        full = os.path.join(root_dir, entry)
        if not os.path.isdir(full):
            continue
        m = _PAN_RE.match(entry)
        if not m:
            continue
        pan = m.group(1)
        if pan not in vault_map:
            continue
        client = vault_map[pan]

        # Find AY sub-folder
        ay_folder_path = ""
        if ay_folder_name:
            candidate = os.path.join(full, ay_folder_name)
            if os.path.isdir(candidate):
                ay_folder_path = candidate

        attachments = collect_attachments(ay_folder_path, pan) if ay_folder_path else []

        results.append({
            "pan": pan,
            "name": client.get("name", ""),
            "email": client.get("email", ""),
            "cc": client.get("cc", ""),
            "ay_folder_path": ay_folder_path,
            "attachments": attachments,
        })

    return results


def collect_attachments(ay_folder: str, pan: str) -> list:
    """Collect 26AS PDF, 26AS Excel, AIS PDF, TIS PDF from ay_folder."""
    if not ay_folder or not os.path.isdir(ay_folder):
        return []

    patterns = [
        f"{pan}-26AS-*.pdf",
        f"{pan}-26AS-*.xlsx",
        f"{pan}-AIS-*.pdf",
        f"{pan}-AIS-*.xlsx",
        f"{pan}-TIS-*.pdf",
    ]
    found = []
    for pat in patterns:
        matches = glob.glob(os.path.join(ay_folder, pat))
        found.extend(sorted(matches))
    return found


def send_email(smtp_cfg: dict, to: str, subject: str, body: str,
               attachments: list = None, cc: list = None, bcc: list = None) -> None:
    """
    Send an email via SMTP.
    cc/bcc are lists of addresses.
    BCC recipients are added to SMTP RCPT TO but not exposed in email headers.
    Raises on failure.
    """
    smtp_from = smtp_cfg.get("smtp_from", "").strip() or smtp_cfg.get("smtp_user", "")

    # Outer container for attachments
    msg = MIMEMultipart("mixed")
    msg["From"] = smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)

    # Append mandatory footer — not editable by user
    _footer_html = (
        "<br><br><hr style='border:none;border-top:1px solid #e5e7eb;margin:16px 0;'>"
        "<p style='font-size:11px;color:#9ca3af;margin:0;'>"
        "Powered by <a href='https://download.aaydoccapio.com/' "
        "style='color:#2563EB;text-decoration:none;'>AayDocCapio</a>"
        "</p>"
    )
    _footer_plain = "\n\n--\nPowered by AayDocCapio (https://download.aaydoccapio.com/)"

    # Build alternative part: plain-text fallback + HTML
    is_html = body.lstrip().startswith("<")
    alt = MIMEMultipart("alternative")
    if is_html:
        full_html = body + _footer_html
        plain = html.unescape(re.sub(r"<[^>]+>", "", body)).strip() + _footer_plain
        alt.attach(MIMEText(plain, "plain", "utf-8"))
        alt.attach(MIMEText(full_html, "html", "utf-8"))
    else:
        alt.attach(MIMEText(body + _footer_plain, "plain", "utf-8"))
    msg.attach(alt)

    for path in (attachments or []):
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{os.path.basename(path)}"',
        )
        msg.attach(part)

    all_rcpt = [to] + (cc or []) + (bcc or [])

    host = smtp_cfg.get("smtp_host", "")
    port = int(smtp_cfg.get("smtp_port", 587))
    user = smtp_cfg.get("smtp_user", "")
    password = smtp_cfg.get("smtp_password", "")
    encryption = smtp_cfg.get("smtp_encryption", "")
    if not encryption:
        encryption = "STARTTLS" if smtp_cfg.get("smtp_use_tls", True) else "SSL/TLS"

    _log(f"--- Connecting: host={host} port={port} encryption={encryption} user={user} from={smtp_from}")

    try:
        if encryption == "STARTTLS":
            server = smtplib.SMTP(host, port, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
        elif encryption == "SSL/TLS":
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)

        try:
            if user and password:
                _log(f"    LOGIN user={user} password={'*' * len(password)}")
                server.login(user, password)
                _log("    LOGIN OK")
            server.sendmail(user, all_rcpt, msg.as_bytes())
            _log(f"    SENT to={to} cc={cc} bcc={bcc}")
        finally:
            server.quit()
    except Exception as e:
        _log(f"    ERROR: {e}")
        raise


def friendly_smtp_error(exc: Exception) -> str:
    """
    Return a short, human-readable message from an SMTP exception.
    Strips the [BeginDiagnosticData]...[EndDiagnosticData] blob that
    Exchange/Outlook appends to 5xx errors.
    """
    msg = str(exc)
    # smtplib wraps errors as (code, b'...' ) tuples — extract the bytes part
    if isinstance(exc, tuple) and len(exc) == 2:
        msg = exc[1].decode(errors="replace") if isinstance(exc[1], bytes) else str(exc[1])
    # Strip Exchange diagnostic blob
    msg = re.sub(r"\[BeginDiagnosticData\].*?\[EndDiagnosticData\]", "", msg, flags=re.DOTALL)
    # Strip trailing hostname annotation
    msg = re.sub(r"\[Hostname=[^\]]*\]", "", msg)
    # smtplib SMTPException often has (code, b'message') — unwrap bytes literals
    msg = re.sub(r"^[\(\d,\s]*(b'|b\")", "", msg.strip())
    msg = msg.strip("'\" ()")
    # Keep first two semicolon segments (code + human reason), drop the rest
    parts = [p.strip() for p in msg.split(";")]
    msg = "; ".join(parts[:2]) if len(parts) >= 2 else parts[0]
    return msg.strip()[:300] or str(exc)


def _parse_addresses(raw: str) -> list:
    """Split a semicolon-separated address string into a clean list."""
    if not raw:
        return []
    return [a.strip() for a in raw.split(";") if a.strip()]


def _doc_list(attachments: list) -> str:
    """Build a numbered HTML list of documents from attachment paths."""
    seen = set()
    entries = []
    for path in attachments:
        fname = os.path.basename(path).upper()
        if "26AS" in fname and fname.endswith(".PDF") and "26AS_PDF" not in seen:
            entries.append("Form 26AS — Annual Tax Statement (PDF)")
            seen.add("26AS_PDF")
        elif "26AS" in fname and fname.endswith(".XLSX") and "26AS_XLS" not in seen:
            entries.append("Form 26AS — Annual Tax Statement (Excel)")
            seen.add("26AS_XLS")
        elif "AIS" in fname and fname.endswith(".PDF") and "AIS_PDF" not in seen:
            entries.append("AIS — Annual Information Statement (PDF)")
            seen.add("AIS_PDF")
        elif "AIS" in fname and fname.endswith(".XLSX") and "AIS_XLS" not in seen:
            entries.append("AIS — Annual Information Statement (Excel)")
            seen.add("AIS_XLS")
        elif "TIS" in fname and "TIS" not in seen:
            entries.append("TIS — Taxpayer Information Summary")
            seen.add("TIS")
    if not entries:
        return "<ol><li>Tax documents</li></ol>"
    items = "".join(f"<li>{e}</li>" for e in entries)
    return f"<ol>{items}</ol>"


def send_batch(smtp_cfg: dict, clients: list, subject_tpl: str, body_tpl: str,
               bcc_addresses: str = "", progress_cb=None) -> dict:
    """
    Send emails to a list of clients.
    Each client dict: {pan, name, email, cc, attachments, ay_label}
    Supports placeholders: {client_name} {pan} {ay} {firm_name} {documents}
    progress_cb(pan, status_str) called after each attempt.
    Returns {pan: "ok" | "error: <reason>"}.
    """
    bcc = _parse_addresses(bcc_addresses)
    results = {}

    for client in clients:
        pan = client.get("pan", "")
        name = client.get("name", "")
        to = client.get("email", "").strip()
        cc = _parse_addresses(client.get("cc", ""))
        ay = client.get("ay_label", "")
        firm = smtp_cfg.get("firm_name", "")
        attachments = client.get("attachments", [])
        documents = _doc_list(attachments)

        fmt = dict(client_name=name, pan=pan, ay=ay, firm_name=firm, documents=documents)
        try:
            subject = subject_tpl.format_map(fmt)
        except Exception:
            subject = subject_tpl
        try:
            # HTML bodies contain CSS braces — only replace known placeholders
            body = body_tpl
            for k, v in fmt.items():
                body = body.replace("{" + k + "}", v)
        except Exception:
            body = body_tpl

        _log(f"--- Client: {name} ({pan}) → {to}")
        try:
            send_email(smtp_cfg, to, subject, body,
                       attachments=attachments, cc=cc, bcc=bcc)
            results[pan] = "ok"
            if progress_cb:
                progress_cb(pan, "✅ Sent")
        except Exception as e:
            reason = friendly_smtp_error(e)
            results[pan] = f"error: {reason}"
            if progress_cb:
                progress_cb(pan, f"❌ Failed — {reason}")

    return results
