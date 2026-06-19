import os
from ui.dialogs import _SMTP_PRESETS  # noqa: E402

# ── Email Help — browser page ─────────────────────────────────────────────────

def _smtp_help_page_html(logo_uri: str, icon_uris: dict) -> str:
    """Return a fully self-contained HTML string for the SMTP help page."""

    hero_logo_html = (
        f'<div style="max-width:700px;width:94%;margin:0 auto 32px;background:#fff;'
        f'border:1px solid rgba(10,22,40,0.10);border-radius:20px;'
        f'box-shadow:0 8px 32px rgba(10,22,40,0.10),0 2px 8px rgba(10,22,40,0.06);'
        f'padding:28px 120px;overflow:hidden;display:flex;align-items:center;justify-content:center;">'
        f'<img src="{logo_uri}" alt="AayDocCapio" style="width:100%;display:block;"/>'
        f'</div>'
        if logo_uri else
        '<div style="margin-bottom:32px;font-family:\'Plus Jakarta Sans\',sans-serif;'
        'font-size:2rem;font-weight:900;color:#09152A;">AayDoc<span style="color:#B88924;">Capio</span>™</div>'
    )

    def provider_icon(name: str, color: str) -> str:
        uri = icon_uris.get(name, "")
        if uri:
            return f'<img src="{uri}" alt="{name}" width="44" height="44" style="border-radius:8px;display:block;">'
        letter = name[0]
        return (f'<div style="width:44px;height:44px;border-radius:8px;background:{color};'
                f'display:flex;align-items:center;justify-content:center;'
                f'color:#fff;font-weight:800;font-size:1.1rem;">{letter}</div>')

    def badge(label: str) -> str:
        return (f'<code style="background:rgba(15,58,104,0.08);color:#0F3A68;'
                f'padding:2px 8px;border-radius:6px;font-size:0.78rem;'
                f'font-family:Consolas,Menlo,monospace;font-weight:600;">{label}</code>')

    def warn_box(msg: str) -> str:
        return (f'<div style="background:#FEF3C7;border:1px solid #FCD34D;border-radius:8px;'
                f'padding:10px 14px;margin:10px 0;display:flex;gap:10px;align-items:flex-start;">'
                f'<span style="font-size:1rem;flex-shrink:0;">⚠️</span>'
                f'<span style="color:#92400E;font-size:0.88rem;line-height:1.55;">{msg}</span>'
                f'</div>')

    def steps_html(items: list) -> str:
        rows = ""
        for i, item in enumerate(items):
            rows += (
                f'<div style="display:flex;gap:12px;align-items:flex-start;margin-bottom:8px;">'
                f'<div style="width:26px;height:26px;border-radius:50%;flex-shrink:0;'
                f'background:linear-gradient(135deg,#2563EB,#0078D4);'
                f'color:#fff;font-weight:700;font-size:0.78rem;'
                f'display:flex;align-items:center;justify-content:center;">{i+1}</div>'
                f'<div style="color:#1A2233;font-size:0.9rem;line-height:1.6;padding-top:3px;">{item}</div>'
                f'</div>'
            )
        return f'<div style="margin:10px 0;">{rows}</div>'

    def bullets_html(items: list) -> str:
        rows = ""
        for item in items:
            rows += (
                f'<div style="display:flex;gap:10px;align-items:flex-start;margin-bottom:6px;">'
                f'<div style="color:#2563EB;font-weight:700;font-size:1rem;flex-shrink:0;line-height:1.5;">•</div>'
                f'<div style="color:#1A2233;font-size:0.9rem;line-height:1.6;">{item}</div>'
                f'</div>'
            )
        return f'<div style="margin:10px 0;">{rows}</div>'

    def option_label(text: str) -> str:
        return (f'<div style="font-weight:700;color:#09152A;font-size:0.9rem;'
                f'margin:12px 0 4px;">{text}</div>')

    def provider_card(name: str, server: str, port: str, enc: str,
                      color: str, body_html: str) -> str:
        return (
            f'<div class="prov-card">'
            f'<div class="prov-body">'
            # header row: icon + name + server badges
            f'<div style="display:flex;gap:14px;align-items:flex-start;margin-bottom:14px;">'
            f'{provider_icon(name, color)}'
            f'<div>'
            f'<div style="font-family:\'Plus Jakarta Sans\',sans-serif;font-weight:700;'
            f'font-size:1rem;color:#09152A;margin-bottom:5px;">{name}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;">'
            f'<span style="font-size:0.78rem;color:#5A6B84;">Server:</span> {badge(server)}'
            f'<span style="font-size:0.78rem;color:#5A6B84;margin-left:4px;">Port:</span> {badge(port)}'
            f'<span style="font-size:0.78rem;color:#5A6B84;margin-left:4px;">Encryption:</span> {badge(enc)}'
            f'</div></div></div>'
            # body
            f'<div>{body_html}</div>'
            f'</div></div>'
        )

    def lnk(url: str, label: str) -> str:
        return f'<a href="https://{url}" target="_blank" rel="noopener" style="color:#2563EB;font-weight:600;">{label}</a>'

    # ── Provider bodies ────────────────────────────────────────────────────────
    gmail_body = (
        '<p style="color:#1A2233;font-size:0.9rem;margin:0 0 6px;">Google blocks your regular password for third-party apps. You must create an <strong>App Password</strong>.</p>'
        + steps_html([
            f'Go to {lnk("myaccount.google.com", "myaccount.google.com")} → Security',
            'Enable <strong>2-Step Verification</strong> (required first)',
            f'Go to {lnk("myaccount.google.com/apppasswords", "myaccount.google.com/apppasswords")}',
            'Select app: <strong>Mail</strong> → Generate',
            'Copy the 16-character password → paste into AayDocCapio',
        ])
        + warn_box("Do NOT use your regular Gmail password. It will always fail.")
    )

    outlook_body = (
        '<p style="color:#1A2233;font-size:0.9rem;margin:0 0 10px;">'
        'This preset covers <strong>personal Microsoft accounts</strong> with these email addresses:</p>'
        + bullets_html([
            '<code style="font-size:0.85rem;">@outlook.com</code> &nbsp; <code style="font-size:0.85rem;">@hotmail.com</code> &nbsp; <code style="font-size:0.85rem;">@live.com</code> &nbsp; <code style="font-size:0.85rem;">@msn.com</code>',
        ])
        + '<p style="color:#B91C1C;font-size:0.88rem;margin:8px 0 10px;font-weight:600;">'
        '⚠ Work or school account (e.g. name@company.com, name@college.edu)? Use <strong>Office 365</strong> instead. This preset will not work for those.</p>'
        + bullets_html([
            'Without MFA: use your regular Outlook.com / Hotmail password.',
            f'With MFA enabled: go to {lnk("mysignins.microsoft.com/security-info", "mysignins.microsoft.com/security-info")} → Add sign-in method → App password → create one and paste it here.',
        ])
    )

    o365_body = (
        warn_box('If MFA is on, your regular password will NOT work even if "Authenticated SMTP" is ticked in Admin Centre. You MUST use an App Password.')
        + option_label('Option 1 (Preferred): App Password, works with or without MFA, no admin needed:')
        + steps_html([
            f'Go to {lnk("mysignins.microsoft.com/security-info", "mysignins.microsoft.com/security-info")}',
            'Click <strong>+ Add sign-in method</strong> → choose <strong>App password</strong> → Next',
            'Enter a name (e.g. AayDocCapio) → Next',
            'Copy the generated password and paste it into AayDocCapio',
        ])
        + option_label('Option 2: Enable Authenticated SMTP (only if MFA is OFF):')
        + steps_html([
            f'Go to {lnk("admin.microsoft.com", "Microsoft 365 Admin Centre")} → Users → [your user] → <strong>Mail</strong> tab',
            'Click <strong>Manage email apps</strong> → tick <strong>Authenticated SMTP</strong> → Save',
        ])
    )

    exchange_body = (
        '<p style="color:#1A2233;font-size:0.9rem;margin:0 0 6px;">Ask your IT/Exchange admin for the SMTP relay address, correct port, and whether authentication is required.</p>'
        + bullets_html([
            'Typical format: <code style="font-size:0.85rem;">mail.yourcompany.com</code>',
            'Port 25 is common for internal relay (no auth needed)',
            'Port 587 with STARTTLS for authenticated SMTP',
        ])
    )

    yahoo_body = (
        '<p style="color:#1A2233;font-size:0.9rem;margin:0 0 6px;">Yahoo requires an <strong>App Password</strong>:</p>'
        + steps_html([
            f'Go to {lnk("login.yahoo.com/account/security", "Yahoo Account Security")}',
            'Click <strong>Generate app password</strong>',
            'Select <strong>Other app</strong> → enter "AayDocCapio" → Get password',
            'Copy and paste into AayDocCapio',
        ])
    )

    icloud_body = (
        '<p style="color:#1A2233;font-size:0.9rem;margin:0 0 6px;">Requires an <strong>App-Specific Password</strong>:</p>'
        + steps_html([
            f'Go to {lnk("appleid.apple.com", "appleid.apple.com")} → Sign-In and Security',
            'Click <strong>App-Specific Passwords</strong> → Generate',
            'Enter label "AayDocCapio" → Create',
            'Copy and paste into AayDocCapio',
        ])
    )

    custom_body = (
        '<p style="color:#1A2233;font-size:0.9rem;margin:0 0 10px;">'
        'Use this when your organisation runs its own mail server or a third-party SMTP relay '
        '(e.g. Amazon SES, SendGrid, Zoho Mail, Brevo, or a cPanel server).</p>'
        + bullets_html([
            '<strong>Host:</strong> the SMTP hostname given by your provider or IT admin (e.g. <code style="font-size:0.85rem;">smtp.zoho.in</code>, <code style="font-size:0.85rem;">email-smtp.ap-south-1.amazonaws.com</code>)',
            '<strong>Port:</strong> typically 587 with STARTTLS, or 465 with SSL/TLS. Port 25 is usually blocked by ISPs.',
            '<strong>Username and Password:</strong> your SMTP credentials — not always the same as your login email.',
            'If your provider gives you an API key instead of a password, paste it in the Password field.',
        ])
        + '<p style="color:#5A6B84;font-size:0.85rem;margin-top:10px;">'
        'Not sure which settings to use? Check your provider\'s documentation under "SMTP settings" or "Outgoing mail server".</p>'
    )

    providers_html = (
        provider_card("Gmail",      "smtp.gmail.com",          "587", "STARTTLS", "#EA4335", gmail_body)
        + provider_card("Outlook.com", "smtp-mail.outlook.com", "587", "STARTTLS", "#0078D4", outlook_body)
        + provider_card("Office 365",  "smtp.office365.com",    "587", "STARTTLS", "#D83B01", o365_body)
        + provider_card("Exchange",    "mail.yourcompany.com",  "587", "STARTTLS", "#0F6CBD", exchange_body)
        + provider_card("Yahoo",       "smtp.mail.yahoo.com",   "587", "STARTTLS", "#6001D2", yahoo_body)
        + provider_card("iCloud",      "smtp.mail.me.com",      "587", "STARTTLS", "#3478F6", icloud_body)
        + provider_card("Custom",      "your.smtp.host",        "587", "STARTTLS", "#64748B", custom_body)
    )

    # ── Troubleshooting rows ───────────────────────────────────────────────────
    trouble_data = [
        ("535 / Authentication failed",  "Wrong password, or regular password used instead of App Password."),
        ("5.7.139 Unsuccessful",          "Office 365 with MFA. Use an App Password (see guide above)."),
        ("Connection timed out",          "Wrong port or firewall blocking SMTP. Try port 465 + SSL/TLS."),
        ("SSL handshake failed",          "Switch between STARTTLS and SSL/TLS, or check the port number."),
        ("Relay access denied",           "SMTP server requires authentication. Verify username and password."),
        ("Clients not receiving",         "Check spam/junk folder at client's end. Check BCC settings."),
    ]
    trouble_rows = ""
    for i, (err, fix) in enumerate(trouble_data):
        row_bg = "#F1F5F9" if i % 2 == 0 else "#FFFFFF"
        trouble_rows += (
            f'<tr style="background:{row_bg};">'
            f'<td style="padding:10px 16px 10px 12px;white-space:nowrap;vertical-align:top;">'
            f'<code style="background:rgba(220,38,38,0.08);color:#B91C1C;padding:3px 8px;'
            f'border-radius:6px;font-size:0.82rem;font-family:Consolas,Menlo,monospace;">{err}</code>'
            f'</td>'
            f'<td style="padding:10px 12px;color:#1A2233;font-size:0.88rem;line-height:1.55;">{fix}</td>'
            f'</tr>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet"/>
  <title>AayDocCapio: Email Setup Help</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:'Inter',-apple-system,"Segoe UI",sans-serif;background:#F3F6FA;
          color:#1A2233;line-height:1.65;font-size:0.97rem;}}
    a{{color:#0F3A68;}} a:hover{{color:#B88924;}}
    nav{{background:linear-gradient(90deg,#0d47a1 0%,#1565c0 40%,#1976d2 100%);
         border-bottom:1px solid rgba(255,255,255,0.15);
         box-shadow:0 2px 16px rgba(13,71,161,0.5);
         padding:0 40px;display:flex;align-items:center;
         justify-content:space-between;height:56px;
         position:sticky;top:0;z-index:100;}}
    .nav-brand{{font-family:'Plus Jakarta Sans',sans-serif;color:#fff;
                font-size:1.05rem;font-weight:800;letter-spacing:-0.01em;}}
    .hero{{background:
      radial-gradient(ellipse 65% 50% at 15% 60%,rgba(15,58,104,0.05) 0%,transparent 55%),
      radial-gradient(ellipse 55% 45% at 85% 20%,rgba(14,165,233,0.05) 0%,transparent 50%),
      linear-gradient(160deg,#F4F7FC 0%,#FFFFFF 50%,#F6F8FC 100%);
      padding:52px 24px 44px;text-align:center;position:relative;overflow:hidden;
      border-bottom:1px solid rgba(10,22,40,0.07);}}
    .hero::before{{content:"";position:absolute;inset:0;
      background-image:radial-gradient(rgba(15,58,104,0.10) 1px,transparent 1px);
      background-size:28px 28px;
      mask-image:radial-gradient(ellipse 75% 70% at 50% 40%,black 20%,transparent 75%);
      -webkit-mask-image:radial-gradient(ellipse 75% 70% at 50% 40%,black 20%,transparent 75%);
      pointer-events:none;}}
    .hero>*{{position:relative;z-index:1;}}
    .hero-badge{{display:inline-flex;align-items:center;gap:8px;
      background:#0A1628;color:#fff;border-radius:999px;
      padding:6px 18px;font-size:0.8rem;font-weight:600;
      letter-spacing:0.3px;margin-bottom:18px;
      box-shadow:0 4px 14px rgba(15,58,104,0.25);}}
    .hero h1{{font-family:'Plus Jakarta Sans',sans-serif;font-size:2rem;font-weight:800;
              color:#09152A;letter-spacing:-0.02em;margin-bottom:12px;}}
    .hero p{{font-size:1rem;color:#5A6B84;max-width:520px;margin:0 auto;line-height:1.7;}}
    .wrap{{max-width:860px;margin:0 auto;padding:0 24px;}}
    section{{padding:60px 0;}}
    section.alt{{background:rgba(241,245,251,0.85);}}
    section+section{{border-top:1px solid rgba(10,22,40,0.07);}}
    section.alt+section,section+section.alt{{border-top:none;}}
    .section-label{{font-family:'Plus Jakarta Sans',sans-serif;font-size:0.7rem;
      font-weight:700;letter-spacing:2.5px;text-transform:uppercase;
      color:#B88924;margin-bottom:8px;}}
    h2{{font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;font-weight:800;
        color:#09152A;margin-bottom:20px;letter-spacing:-0.02em;}}
    .enc-grid{{display:flex;flex-direction:column;gap:10px;margin-top:16px;}}
    .enc-item{{display:flex;gap:14px;align-items:flex-start;
      background:#fff;border:1px solid rgba(10,22,40,0.08);
      border-left:3px solid #2563EB;border-radius:10px;
      padding:14px 18px;
      box-shadow:0 1px 3px rgba(10,22,40,0.05);}}
    .enc-name{{font-family:Consolas,Menlo,monospace;font-weight:700;
      font-size:0.85rem;color:#2563EB;min-width:80px;padding-top:1px;}}
    .enc-desc{{color:#1A2233;font-size:0.9rem;line-height:1.6;}}
    .prov-card{{
      background:#FFFFFF;border:1px solid rgba(10,22,40,0.09);
      border-radius:14px;margin-bottom:16px;overflow:hidden;
      box-shadow:0 2px 8px rgba(10,22,40,0.06),0 8px 24px rgba(10,22,40,0.07);
      position:relative;
      transition:transform 240ms cubic-bezier(0.33,1,0.68,1),
                 box-shadow 240ms cubic-bezier(0.33,1,0.68,1),
                 border-color 240ms cubic-bezier(0.33,1,0.68,1);}}
    .prov-card::before{{
      content:"";position:absolute;left:0;right:0;top:0;height:3px;
      background:linear-gradient(90deg,#0F3A68,#0078D4,#B88924);
      border-radius:14px 14px 0 0;}}
    .prov-card::after{{
      content:"";position:absolute;inset:0;border-radius:inherit;
      background:radial-gradient(
        500px circle at var(--mouse-x,50%) var(--mouse-y,50%),
        rgba(15,58,104,0.07),transparent 40%);
      opacity:0;
      transition:opacity 240ms cubic-bezier(0.33,1,0.68,1);
      pointer-events:none;}}
    .prov-card:hover{{
      transform:translateY(-4px);
      border-color:rgba(15,58,104,0.25);
      box-shadow:0 0 0 1px rgba(15,58,104,0.08),
                 0 12px 36px rgba(10,22,40,0.13),
                 0 4px 12px rgba(10,22,40,0.07);}}
    .prov-card:hover::after{{opacity:1;}}
    .prov-body{{padding:18px 22px 20px;}}
    table.trouble{{width:100%;border-collapse:collapse;border-radius:12px;overflow:hidden;
      border:1px solid rgba(10,22,40,0.09);
      box-shadow:0 2px 8px rgba(10,22,40,0.05);}}
    .footer-strip{{background:linear-gradient(90deg,#0A1628 0%,#0F3A68 50%,#0A1628 100%);
      color:rgba(255,255,255,0.7);text-align:center;padding:20px 24px;
      font-size:0.85rem;border-top:1px solid rgba(255,255,255,0.06);}}
    .footer-strip strong{{color:#F5C96B;}}
  </style>
</head>
<body>

<!-- NAV -->
<nav>
  <span class="nav-brand">AayDoc <span style="color:#B88924;">Capio</span>™</span>
  <span class="nav-brand" style="font-size:0.82rem;font-weight:500;opacity:0.75;letter-spacing:0;">✉ Email Setup Help</span>
</nav>

<!-- HERO -->
<div class="hero">
  {hero_logo_html}
  <div class="hero-badge">✉ SMTP Configuration Guide</div>
  <p>Configure AayDocCapio to send tax documents directly to your clients using your existing email account.</p>
</div>

<!-- SECTION 1: What is SMTP -->
<section>
  <div class="wrap">
    <div class="section-label">Getting Started</div>
    <h2>What is SMTP?</h2>
    <p style="color:#1A2233;font-size:0.97rem;line-height:1.75;max-width:720px;">
      SMTP is the protocol used to <strong>send</strong> email. AayDocCapio uses your existing
      email account to deliver tax documents to clients. Your password is stored
      <strong>AES-256 encrypted</strong> in the local vault. It never leaves your machine.
    </p>

    <div style="margin-top:28px;">
      <div class="section-label" style="margin-bottom:12px;">Encryption Options</div>
      <div class="enc-grid">
        <div class="enc-item">
          <div class="enc-name">STARTTLS</div>
          <div class="enc-desc">Starts unencrypted, upgrades to TLS. Use with <strong>port 587</strong>. Recommended for all major providers.</div>
        </div>
        <div class="enc-item">
          <div class="enc-name">SSL/TLS</div>
          <div class="enc-desc">Encrypted from the start. Use with <strong>port 465</strong>. Gmail supports this as an alternative.</div>
        </div>
        <div class="enc-item" style="border-left-color:#DC2626;">
          <div class="enc-name" style="color:#DC2626;">None</div>
          <div class="enc-desc">No encryption. Only for internal/local SMTP relays. <strong>Never use for public email.</strong></div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- SECTION 2: Provider Guide -->
<section class="alt">
  <div class="wrap">
    <div class="section-label">Supported Providers</div>
    <h2>Provider Guide</h2>
    {providers_html}
  </div>
</section>

<!-- SECTION 3: Troubleshooting -->
<section>
  <div class="wrap">
    <div class="section-label">Common Errors</div>
    <h2>Troubleshooting</h2>
    <table class="trouble">
      <thead>
        <tr style="background:#0A1628;">
          <th style="padding:11px 16px;text-align:left;color:rgba(255,255,255,0.85);
                     font-size:0.82rem;font-weight:600;letter-spacing:0.5px;white-space:nowrap;">Error</th>
          <th style="padding:11px 16px;text-align:left;color:rgba(255,255,255,0.85);
                     font-size:0.82rem;font-weight:600;letter-spacing:0.5px;">What to do</th>
        </tr>
      </thead>
      <tbody>{trouble_rows}</tbody>
    </table>
  </div>
</section>

<!-- FOOTER -->
<div class="footer-strip">
  <strong>AayDocCapio</strong> &nbsp;•&nbsp; Email Setup Help &nbsp;•&nbsp;
  <span style="opacity:0.6;">You can close this tab when done.</span>
</div>

<script>
  // Fluent reveal highlight — track mouse position per card (same as landing page)
  (function() {{
    document.querySelectorAll('.prov-card').forEach(function(card) {{
      card.addEventListener('mousemove', function(e) {{
        var rect = card.getBoundingClientRect();
        card.style.setProperty('--mouse-x', ((e.clientX - rect.left) / rect.width * 100).toFixed(1) + '%');
        card.style.setProperty('--mouse-y', ((e.clientY - rect.top) / rect.height * 100).toFixed(1) + '%');
      }});
    }});
  }})();
</script>
</body>
</html>"""


def _write_smtp_help_html() -> str:
    """Generate the SMTP help page, write to a temp file, return the file path."""
    import base64 as _b64mod, tempfile
    from config import _bundled_dir

    def _b64(rel: str) -> str:
        p = os.path.join(_bundled_dir(), rel)
        if not os.path.isfile(p):
            return ""
        with open(p, "rb") as f:
            data = _b64mod.b64encode(f.read()).decode()
        return f"data:image/png;base64,{data}"

    logo_uri = _b64("resources/AayDoc_FullLogo.png")
    icon_uris = {
        p["name"]: _b64(f"resources/icons/{p['icon_file']}")
        for p in _SMTP_PRESETS if p.get("icon_file")
    }

    html = _smtp_help_page_html(logo_uri, icon_uris)
    out = os.path.join(tempfile.gettempdir(), "aay_smtp_help.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out

