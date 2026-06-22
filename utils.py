import datetime
import os
import subprocess
import sys


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
