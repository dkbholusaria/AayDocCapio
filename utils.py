import datetime
import glob
import os
import shutil
import subprocess
import sys

# Old installs saved 26AS/Form 168/AIS/TIS files flat in the per-client-per-year
# folder. Newer versions organize them into subfolders by document type. This
# table drives a lazy, idempotent, one-directional migration of any leftover
# flat files — run wherever that folder gets touched (a new download, or the
# emailer scanning it), never as a single upfront full-tree scan at startup.
_LEGACY_FLAT_PATTERNS = (
    ("*-26AS-*", "26AS"),
    ("*-168-*", "26AS"),
    ("*-AIS-*", "AIS-TIS"),
    ("*-TIS-*", "AIS-TIS"),
)


def migrate_flat_docs_to_subfolders(ay_folder: str, log_callback=None) -> None:
    """
    One-directional, best-effort migration of old flat-layout files (from
    pre-subfolder-reorg versions) into their new document-type subfolders.
    Non-recursive glob directly in ay_folder, so already-migrated files sitting
    inside subfolders never match again — safe to call on every visit to this
    folder. Never raises: a migration hiccup must not block a download or an
    email send.
    """
    try:
        if not os.path.isdir(ay_folder):
            return
        for pattern, subfolder in _LEGACY_FLAT_PATTERNS:
            for src in glob.glob(os.path.join(ay_folder, pattern)):
                if not os.path.isfile(src):
                    continue
                dest_dir = os.path.join(ay_folder, subfolder)
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, os.path.basename(src))
                if os.path.exists(dest):
                    continue  # already migrated (or a same-named file exists) — leave the flat copy alone
                shutil.move(src, dest)
                if log_callback:
                    log_callback(f"[Migrate] Moved {os.path.basename(src)} -> {subfolder}/")
    except Exception as e:
        if log_callback:
            log_callback(f"[Migrate] Skipped folder migration for {ay_folder}: {e}")


def migrate_itr_filing_subfolder(download_dir: str, filing_type: str, filing_date_ddmmyyyy: str,
                                  ack_no: str, log_callback=None) -> None:
    """
    Filed Returns subfolders were originally named "{filing_type}-{date}",
    then changed to "{filing_type}-{date}-{ack_no}" once it was confirmed
    live that type+date alone can collide (a discarded-then-refiled Original
    sharing both with the return that replaced it). Old installs left
    old-style folders behind; without this, re-running the same filing after
    upgrading creates a second, ack_no-suffixed folder alongside the old one
    instead of continuing to use it — same duplicate-folder problem the
    ack_no fix was meant to solve, just from the other direction.

    Best-effort, one-directional: if the old-style folder exists and the new
    one doesn't, rename it; if both exist, move any files from the old one
    into the new one (skipping anything already present) and remove the old
    folder if it ends up empty. Never raises — a migration hiccup must not
    block a download.
    """
    if not ack_no:
        return  # old and new names are identical when there's no ack_no
    try:
        old_name = f"{filing_type}-{filing_date_ddmmyyyy}"
        new_name = f"{filing_type}-{filing_date_ddmmyyyy}-{ack_no}"
        for subfolder in ("ITR Returns", "Intimation Orders"):
            old_dir = os.path.join(download_dir, subfolder, old_name)
            new_dir = os.path.join(download_dir, subfolder, new_name)
            if not os.path.isdir(old_dir):
                continue
            if not os.path.isdir(new_dir):
                os.makedirs(os.path.join(download_dir, subfolder), exist_ok=True)
                shutil.move(old_dir, new_dir)
                if log_callback:
                    log_callback(f"[Migrate] Renamed {subfolder}/{old_name} -> {new_name}")
                continue
            moved_any = False
            for name in os.listdir(old_dir):
                src = os.path.join(old_dir, name)
                dest = os.path.join(new_dir, name)
                if os.path.exists(dest):
                    continue
                shutil.move(src, dest)
                moved_any = True
            if moved_any and log_callback:
                log_callback(f"[Migrate] Merged {subfolder}/{old_name} -> {new_name}")
            if not os.listdir(old_dir):
                os.rmdir(old_dir)
    except Exception as e:
        if log_callback:
            log_callback(f"[Migrate] Skipped ITR subfolder migration for {filing_type}-{filing_date_ddmmyyyy}: {e}")


def get_timestamp() -> str:
    """Return current time in Asia/Kolkata as DD-MM-YYYY HH:MM:SS."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    return now.strftime("%d-%m-%Y %H:%M:%S")


def notify_windows(title: str, message: str) -> None:
    """Fire a Windows toast notification via PowerShell. No-op on non-Windows."""
    if sys.platform != "win32":
        return
    try:
        # Resolve PNG icon path — toast XML requires PNG, not ICO
        if getattr(sys, "frozen", False):
            _base = os.path.dirname(sys.executable)
        else:
            _base = os.path.dirname(os.path.abspath(__file__))
        icon_png = os.path.join(_base, "resources", "app_icon.png")
        # Escape backslashes for PowerShell string and XML attribute
        icon_xml = icon_png.replace("\\", "/")

        img_tag = f'<image placement="appLogoOverride" src="file:///{icon_xml}"/>' \
            if os.path.isfile(icon_png) else ""

        ps = f"""
$ErrorActionPreference = 'Stop'
try {{
    $reg = 'HKCU:\\SOFTWARE\\Classes\\AppUserModelId\\AayDocCapio'
    New-Item -Path $reg -Force | Out-Null
    New-ItemProperty -Path $reg -Name 'DisplayName' -Value 'AayDocCapio' -PropertyType String -Force | Out-Null
    $null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
    $null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml('<toast><visual><binding template="ToastGeneric">{img_tag}<text>{title}</text><text>{message}</text></binding></visual></toast>')
    $toast    = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AayDocCapio')
    $notifier.Show($toast)
}} catch {{
    [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null
    [System.Windows.Forms.MessageBox]::Show('{message}', '{title}')
}}
"""
        subprocess.Popen(
            ["powershell", "-NonInteractive", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-Command", ps],
            creationflags=0x08000000,   # CREATE_NO_WINDOW
        )
    except Exception:
        pass
