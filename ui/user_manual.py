import os

# ── User Manual HTML ──────────────────────────────────────────────────────────

def _user_manual_page_html(img_uris: dict) -> str:
    """Return a fully self-contained HTML string for the user help manual."""

    def _img(key: str, caption: str, alt: str) -> str:
        uri = img_uris.get(key, "")
        if uri:
            return (
                f'<figure style="margin:20px 0;text-align:center;">'
                f'<img src="{uri}" alt="{alt}" style="max-width:100%;border-radius:10px;'
                f'border:1px solid rgba(10,22,40,0.12);box-shadow:0 4px 16px rgba(10,22,40,0.10);display:inline-block;"/>'
                f'<figcaption style="margin-top:8px;font-size:0.82rem;color:#5A6B84;font-style:italic;">{caption}</figcaption>'
                f'</figure>'
            )
        return (
            f'<figure style="margin:20px 0;text-align:center;">'
            f'<div style="background:#F1F5F9;border:2px dashed #CBD5E1;border-radius:10px;'
            f'padding:40px 24px;color:#94A3B8;font-size:0.88rem;">'
            f'[Screenshot: {caption}]</div>'
            f'<figcaption style="margin-top:8px;font-size:0.82rem;color:#5A6B84;font-style:italic;">{caption}</figcaption>'
            f'</figure>'
        )

    def warn_box(msg: str) -> str:
        return (
            f'<div style="background:#FEF3C7;border:1px solid #FCD34D;border-radius:8px;'
            f'padding:10px 14px;margin:12px 0;display:flex;gap:10px;align-items:flex-start;">'
            f'<span style="font-size:1rem;flex-shrink:0;">⚠️</span>'
            f'<span style="color:#92400E;font-size:0.88rem;line-height:1.55;">{msg}</span>'
            f'</div>'
        )

    def tip_box(msg: str) -> str:
        return (
            f'<div style="background:#ECFDF5;border:1px solid #6EE7B7;border-radius:8px;'
            f'padding:10px 14px;margin:12px 0;display:flex;gap:10px;align-items:flex-start;">'
            f'<span style="font-size:1rem;flex-shrink:0;">💡</span>'
            f'<span style="color:#065F46;font-size:0.88rem;line-height:1.55;">{msg}</span>'
            f'</div>'
        )

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

    def badge(label: str) -> str:
        return (
            f'<code style="background:rgba(15,58,104,0.08);color:#0F3A68;'
            f'padding:2px 8px;border-radius:6px;font-size:0.78rem;'
            f'font-family:Consolas,Menlo,monospace;font-weight:600;">{label}</code>'
        )

    def err_badge(label: str) -> str:
        return (
            f'<code style="background:rgba(220,38,38,0.08);color:#B91C1C;'
            f'padding:3px 8px;border-radius:6px;font-size:0.82rem;'
            f'font-family:Consolas,Menlo,monospace;">{label}</code>'
        )

    def section_card(body_html: str) -> str:
        return (
            f'<div class="info-card">'
            f'<div class="info-card-body">{body_html}</div>'
            f'</div>'
        )

    def h3(text: str) -> str:
        return (
            f'<h3 style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:1.05rem;'
            f'font-weight:700;color:#09152A;margin:24px 0 10px;">{text}</h3>'
        )

    # ── Status icon table ──────────────────────────────────────────────────────
    status_rows = [
        ("✅", "green", "Downloaded (and unlocked if applicable)", "Document saved to the output folder successfully."),
        ("⚠️", "amber", "Downloaded but still locked", "File was saved but PDF unlock failed — usually wrong DOB. Open the file manually with the password."),
        ("🕐", "blue",  "AIS queued — check back later", "AIS PDF generation was requested. Re-run the download the next day."),
        ("⬜", "grey",  "No data for this year", "The portal has no 26AS or AIS data for this client and year."),
        ("❌", "red",   "Failed", "Login failed, portal error, or download timed out. Check the error message for details."),
        ("⏹", "grey",  "Skipped / aborted", "Batch was stopped before this client ran."),
    ]
    status_table_rows = ""
    for icon, _color, short, detail in status_rows:
        status_table_rows += (
            f'<tr>'
            f'<td style="padding:10px 14px;font-size:1.1rem;text-align:center;white-space:nowrap;">{icon}</td>'
            f'<td style="padding:10px 14px;font-weight:600;color:#09152A;font-size:0.9rem;white-space:nowrap;">{short}</td>'
            f'<td style="padding:10px 14px;color:#1A2233;font-size:0.88rem;line-height:1.55;">{detail}</td>'
            f'</tr>'
        )

    # ── Common problems table ──────────────────────────────────────────────────
    problems = [
        ("❌ Invalid Password",
         "The portal password stored in the vault is wrong or outdated.",
         "Open the client record (••• → Edit), update the password, and re-run."),
        ("❌ AUTHENTICATION FAILED: 2FA enabled",
         "The client has Two-Step Authentication turned on in the ITD portal.",
         "Ask the client to log into the ITD portal → Profile → My Profile → Login Settings → disable Two-Step Authentication."),
        ("❌ Already logged in on another device",
         "The client has an active session open in a browser.",
         "Wait a few minutes for the session to expire, or ask the client to log out, then retry."),
        ("⚠️ AIS locked — wrong password",
         "The PDF was downloaded but the unlock attempt failed because the DOB in the vault does not match.",
         f'Verify the Date of Birth in the client record. AIS/TIS password format: {badge("lowercase_pan + DDMMYYYY")} e.g. {badge("aaapt0001a01011980")}'),
        ("⬜ AIS — no data for this FY",
         "The Insight portal has no AIS data for this client for the selected year.",
         "This is normal for newer clients or years with no transactions. No action needed."),
        ("⬜ AIS too large — use AIS Utility",
         "The portal cannot generate the PDF for very large AIS datasets.",
         "Download the AIS JSON from the portal manually and use the AIS Utility desktop app. Automated support is planned for a future release."),
        ("❌ 26AS too large for inline download",
         "TRACES does not serve the file through the ITD portal for very large 26AS data.",
         "Log directly into tdscpc.gov.in and place a manual download request. Automated TRACES-direct flow is planned."),
        ("ZIP password wrong / TXT not extracted",
         f'The 26AS ZIP password is the DOB in {badge("DDMMYYYY")} format. If the DOB is wrong, the ZIP cannot be extracted.',
         "Check the DOB in the client record (••• → Edit) and correct it."),
    ]
    prob_rows = ""
    for i, (err, cause, fix) in enumerate(problems):
        row_bg = "#F1F5F9" if i % 2 == 0 else "#FFFFFF"
        prob_rows += (
            f'<tr style="background:{row_bg};">'
            f'<td style="padding:10px 14px;vertical-align:top;">'
            f'{err_badge(err)}</td>'
            f'<td style="padding:10px 14px;color:#1A2233;font-size:0.85rem;line-height:1.55;vertical-align:top;">{cause}</td>'
            f'<td style="padding:10px 14px;color:#1A2233;font-size:0.85rem;line-height:1.55;vertical-align:top;">{fix}</td>'
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
  <title>AayDocCapio — User Guide</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:'Inter',-apple-system,"Segoe UI",sans-serif;background:#F3F6FA;
          color:#1A2233;line-height:1.65;font-size:0.97rem;}}
    a{{color:#2563EB;}} a:hover{{color:#1D4ED8;text-decoration:underline;}}
    nav{{background:linear-gradient(90deg,#0d47a1 0%,#1565c0 40%,#1976d2 100%);
         border-bottom:1px solid rgba(255,255,255,0.15);
         box-shadow:0 2px 16px rgba(13,71,161,0.5);
         padding:0 40px;display:flex;align-items:center;
         justify-content:space-between;height:56px;
         position:sticky;top:0;z-index:100;}}
    .nav-brand{{font-family:'Plus Jakarta Sans',sans-serif;color:#fff;
                font-size:1.05rem;font-weight:800;letter-spacing:-0.01em;}}
    .nav-links{{display:flex;gap:4px;}}
    .nav-links a{{color:rgba(255,255,255,0.80);font-size:0.82rem;font-weight:500;
                  text-decoration:none;padding:6px 12px;border-radius:6px;
                  transition:background 150ms;}}
    .nav-links a:hover{{background:rgba(255,255,255,0.15);color:#fff;text-decoration:none;}}
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
    .hero p{{font-size:1rem;color:#5A6B84;max-width:560px;margin:0 auto;line-height:1.7;}}
    
    /* Layout split container */
    .main-layout {{
      display: flex;
      max-width: 1280px;
      margin: 0 auto;
      padding: 40px 24px;
      gap: 36px;
    }}
    .sidebar {{
      width: 280px;
      flex-shrink: 0;
      position: sticky;
      top: 96px;
      height: calc(100vh - 136px);
      overflow-y: auto;
      padding-right: 12px;
      border-right: 1px solid rgba(10,22,40,0.06);
    }}
    .sidebar-nav {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .sidebar-nav-item {{
      display: flex;
      align-items: center;
      padding: 10px 14px;
      border-radius: 8px;
      color: #5A6B84;
      font-size: 0.88rem;
      font-weight: 500;
      text-decoration: none;
      transition: all 150ms;
      line-height: 1.35;
    }}
    .sidebar-nav-item:hover {{
      background: rgba(15, 58, 104, 0.04);
      color: #0F3A68;
      text-decoration: none;
    }}
    .sidebar-nav-item.active {{
      background: #EFF6FF;
      color: #2563EB;
      font-weight: 600;
      border-left: 3px solid #2563EB;
      border-top-left-radius: 0;
      border-bottom-left-radius: 0;
    }}
    
    /* Nested sidebar styling */
    .sidebar-group {{
      display: flex;
      flex-direction: column;
      gap: 2px;
    }}
    .sidebar-nav-item.sub-item {{
      padding: 6px 14px 6px 28px;
      font-size: 0.81rem;
      color: #64748B;
    }}
    .sidebar-nav-item.sub-item:hover {{
      background: rgba(15, 58, 104, 0.03);
      color: #0F3A68;
    }}
    .sidebar-nav-item.sub-item.active {{
      background: #F0F7FF;
      color: #1D4ED8;
      font-weight: 600;
      border-left: 2px solid #1D4ED8;
      border-top-left-radius: 0;
      border-bottom-left-radius: 0;
    }}
    
    .sidebar-nav-item.sub-sub-item {{
      padding: 6px 14px 6px 42px;
      font-size: 0.78rem;
      color: #64748B;
    }}
    .sidebar-nav-item.sub-sub-item:hover {{
      background: rgba(15, 58, 104, 0.03);
      color: #0F3A68;
    }}
    .sidebar-nav-item.sub-sub-item.active {{
      background: #F0F7FF;
      color: #1D4ED8;
      font-weight: 600;
      border-left: 2px solid #1D4ED8;
      border-top-left-radius: 0;
      border-bottom-left-radius: 0;
    }}

    /* Collapsible Logic */
    .sidebar-group .sub-item,
    .sidebar-group .sub-sub-item {{
      max-height: 0;
      opacity: 0;
      overflow: hidden;
      padding-top: 0;
      padding-bottom: 0;
      margin-top: 0;
      margin-bottom: 0;
      pointer-events: none;
      border-left-width: 0 !important;
      transition: max-height 0.2s ease-out, opacity 0.2s ease-out, padding 0.2s ease-out, margin 0.2s ease-out;
    }}
    
    .sidebar-group.active .sub-item {{
      max-height: 50px;
      opacity: 1;
      pointer-events: auto;
      padding: 6px 14px 6px 28px;
      margin-top: 2px;
      border-left-width: 2px !important;
    }}
    .sidebar-group.active .sub-sub-item {{
      max-height: 50px;
      opacity: 1;
      pointer-events: auto;
      padding: 6px 14px 6px 42px;
      margin-top: 2px;
      border-left-width: 2px !important;
    }}

    .content-area {{
      flex: 1;
      min-width: 0;
    }}
    .content-area section {{
      padding-bottom: 52px;
      scroll-margin-top: 80px;
    }}
    .content-area section:not(:last-of-type) {{
      border-bottom: 1px solid rgba(10,22,40,0.07);
      margin-bottom: 48px;
    }}
    .content-area .wrap {{
      max-width: 100%;
      padding: 0;
    }}

    .info-card{{background:#FFFFFF;border:1px solid rgba(10,22,40,0.09);
      border-radius:14px;margin-bottom:16px;overflow:hidden;
      box-shadow:0 2px 8px rgba(10,22,40,0.06),0 8px 24px rgba(10,22,40,0.07);
      position:relative;
      transition:transform 240ms cubic-bezier(0.33,1,0.68,1),
                 box-shadow 240ms cubic-bezier(0.33,1,0.68,1),
                 border-color 240ms cubic-bezier(0.33,1,0.68,1);}}
    .info-card::before{{content:"";position:absolute;left:0;right:0;top:0;height:3px;
      background:linear-gradient(90deg,#0F3A68,#0078D4,#B88924);
      border-radius:14px 14px 0 0;}}
    .info-card::after{{content:"";position:absolute;inset:0;border-radius:inherit;
      background:radial-gradient(500px circle at var(--mouse-x,50%) var(--mouse-y,50%),
        rgba(15,58,104,0.07),transparent 40%);
      opacity:0;transition:opacity 240ms cubic-bezier(0.33,1,0.68,1);pointer-events:none;}}
    .info-card:hover{{transform:translateY(-2px);border-color:rgba(15,58,104,0.20);
      box-shadow:0 0 0 1px rgba(15,58,104,0.08),0 10px 30px rgba(10,22,40,0.11);}}
    .info-card:hover::after{{opacity:1;}}
    .info-card-body{{padding:20px 24px 22px;}}
    table.data-table{{width:100%;border-collapse:collapse;border-radius:12px;overflow:hidden;
      border:1px solid rgba(10,22,40,0.09);box-shadow:0 2px 8px rgba(10,22,40,0.05);}}
    table.data-table thead tr{{background:#0A1628;}}
    table.data-table thead th{{padding:11px 14px;text-align:left;color:rgba(255,255,255,0.85);
      font-size:0.82rem;font-weight:600;letter-spacing:0.5px;}}
    table.data-table tbody tr:nth-child(even){{background:#F1F5F9;}}
    table.data-table tbody tr:nth-child(odd){{background:#FFFFFF;}}
    .footer-strip{{background:linear-gradient(90deg,#0A1628 0%,#0F3A68 50%,#0A1628 100%);
      color:rgba(255,255,255,0.7);text-align:center;padding:20px 24px;
      font-size:0.85rem;border-top:1px solid rgba(255,255,255,0.06);}}
    .footer-strip strong{{color:#F5C96B;}}
    details summary{{cursor:pointer;font-weight:600;color:#09152A;padding:4px 0;
      list-style:none;display:flex;align-items:center;gap:8px;}}
    details summary::before{{content:"▶";font-size:0.65rem;color:#2563EB;
      transition:transform 200ms;display:inline-block;}}
    details[open] summary::before{{transform:rotate(90deg);}}
    details+details{{border-top:1px solid rgba(10,22,40,0.07);margin-top:4px;}}
    details{{padding:10px 0;}}
    details p{{color:#1A2233;font-size:0.9rem;line-height:1.65;margin-top:8px;padding-left:20px;}}
    .floating-top{{position:fixed;bottom:20px;right:20px;background:#0F3A68;color:#fff;
                   width:40px;height:40px;border-radius:50%;display:flex;align-items:center;
                   justify-content:center;text-decoration:none;box-shadow:0 4px 12px rgba(0,0,0,0.15);
                   z-index:99;font-weight:bold;font-size:1.1rem;transition:all 150ms;}}
    .floating-top:hover{{background:#2563EB;transform:translateY(-2px);}}
  </style>
</head>
<body>

<!-- NAV -->
<nav>
  <span class="nav-brand">AayDoc <span style="color:#B88924;">Capio</span>™</span>
  <div class="nav-links">
    <a href="https://deepak.bholusaria.com" target="_blank" rel="noopener">Contact us</a>
  </div>
</nav>

<!-- HERO -->
<div class="hero">
  <div class="hero-badge">📖 Complete User Guide & Manual</div>
  <h1 id="hero-title">AayDocCapio Help Center</h1>
  <p>Your comprehensive self-service guide for automated bulk retrieval of tax documents from the ITD portal.</p>
</div>

<!-- MAIN LAYOUT -->
<div class="main-layout">
  <!-- SIDEBAR NAVIGATOR -->
  <aside class="sidebar">
    <div class="sidebar-nav">
      <div class="sidebar-group">
        <a href="#overview" class="sidebar-nav-item active">1. Overview</a>
        <a href="#what-is-adc" class="sidebar-nav-item sub-item">1.1. What is AayDocCapio?</a>
        <a href="#no-cloud-privacy" class="sidebar-nav-item sub-item">1.2. Privacy Guarantee</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#getting-started" class="sidebar-nav-item">2. Getting Started</a>
        <a href="#system-requirements" class="sidebar-nav-item sub-item">2.1. System Requirements</a>
        <a href="#initial-setup" class="sidebar-nav-item sub-item">2.2. Setup Checklist</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#managing-clients" class="sidebar-nav-item">3. Managing Clients</a>
        <a href="#client-profiles" class="sidebar-nav-item sub-item">3.1. Client Profiles</a>
        <a href="#importance-of-dob" class="sidebar-nav-item sub-item">3.2. DOB Importance</a>
        <a href="#bulk-import-export" class="sidebar-nav-item sub-item">3.3. Bulk Import & Export</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#bulk-download" class="sidebar-nav-item">4. Bulk Download</a>
        <a href="#select-clients-year" class="sidebar-nav-item sub-item">4.1. Setup & Select</a>
        <a href="#bulk-26as-download" class="sidebar-nav-item sub-item">4.2. Bulk 26AS Download</a>
        <a href="#bulk-ais-download" class="sidebar-nav-item sub-item">4.3. Bulk AIS Download</a>
        <a href="#menu-options-download" class="sidebar-nav-item sub-item">4.4. Menu Options to Click</a>
        <a href="#status-indicators" class="sidebar-nav-item sub-item">4.5. Status Icons & Controls</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#form-26as-details" class="sidebar-nav-item">5. Form 26AS Details</a>
        <a href="#double-formats" class="sidebar-nav-item sub-item">5.1. PDF & TXT Formats</a>
        <a href="#zip-extraction" class="sidebar-nav-item sub-item">5.2. ZIP Extraction</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#ais-tis-details" class="sidebar-nav-item">6. AIS & TIS Details</a>
        <a href="#ais-tis-diffs" class="sidebar-nav-item sub-item">6.1. Key Differences</a>
        <a href="#two-phase-queue" class="sidebar-nav-item sub-item">6.2. Two-Phase Retrieval</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#pdf-decryption" class="sidebar-nav-item">7. PDF Decryption</a>
        <a href="#decryption-rules" class="sidebar-nav-item sub-item">7.1. Decryption Rules</a>
        <a href="#decryption-troubleshooting" class="sidebar-nav-item sub-item">7.2. Decryption Troubleshooting</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#tools-menu-section" class="sidebar-nav-item">8. Tools Menu Utilities</a>
        <a href="#tools-26as" class="sidebar-nav-item sub-item">8.1. Convert 26AS TXT</a>
        <a href="#tools-ais" class="sidebar-nav-item sub-item">8.2. Convert AIS JSON</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#email-setup-delivery" class="sidebar-nav-item">9. Email Setup & Mailing</a>
        <a href="#how-to-setup-email" class="sidebar-nav-item sub-item">9.1. How to Setup Email</a>
        <a href="#email-settings-reference" class="sidebar-nav-item sub-item">9.2. Email Settings Reference</a>
        <a href="#gmail-setup-ref" class="sidebar-nav-item sub-sub-item">9.2.1. Gmail & Workspace</a>
        <a href="#office365-setup-ref" class="sidebar-nav-item sub-sub-item">9.2.2. Microsoft 365</a>
        <a href="#yahoo-icloud-setup-ref" class="sidebar-nav-item sub-sub-item">9.2.3. Yahoo & iCloud</a>
        <a href="#custom-exchange-ref" class="sidebar-nav-item sub-sub-item">9.2.4. Custom & Exchange</a>
        <a href="#automated-mailing" class="sidebar-nav-item sub-item">9.3. Mailing Documents</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#settings-customization" class="sidebar-nav-item">10. Settings & Sub-sections</a>
        <a href="#settings-folder" class="sidebar-nav-item sub-item">10.1. Download Folder Path</a>
        <a href="#settings-ay" class="sidebar-nav-item sub-item">10.2. Manage Assessment Years</a>
        <a href="#settings-appearance" class="sidebar-nav-item sub-item">10.3. Appearance & Themes</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#app-updates" class="sidebar-nav-item">11. Software Updates</a>
        <a href="#inbuilt-auto-update" class="sidebar-nav-item sub-item">11.1. Inbuilt Auto-Update</a>
      </div>
      
      <div class="sidebar-group">
        <a href="#troubleshooting-faq" class="sidebar-nav-item">12. Troubleshooting & FAQ</a>
        <a href="#error-resolutions" class="sidebar-nav-item sub-item">12.1. Common Portal Errors</a>
        <a href="#faq-list" class="sidebar-nav-item sub-item">12.2. Frequently Asked Qs</a>
      </div>
    </div>
  </aside>

  <!-- MAIN CONTENT AREA -->
  <main class="content-area">

    <!-- SECTION 1: Overview -->
    <section id="overview">
      <div class="wrap">
        <div class="section-label">Section 1</div>
        <h2>Overview</h2>
        
        <div id="what-is-adc" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("1.1. What is AayDocCapio?") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'AayDocCapio is a professional-grade desktop application built specifically for Chartered Accountants (CAs), '
            f'tax practitioners, and financial auditors. It automates the tedious, repetitive process of logging into '
            f'the Income Tax Department (ITD) portal to retrieve key tax compliance documents for multiple clients.</p>'
            + bullets_html([
              '<strong>Bulk Automation</strong>: Replaces hours of manual login, navigation, and file downloading with a single click.',
              '<strong>Supported Statements</strong>: Fetches Form 26AS (TXT + PDF), Annual Information Statement (AIS PDF + JSON), and Taxpayer Information Summary (TIS PDF).',
              '<strong>Local Decryption</strong>: Automatically decrypts downloaded files, delivering clean, password-free documents to your output folders.',
            ])
          )}
        </div>

        <div id="no-cloud-privacy" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("1.2. No-Cloud Privacy Guarantee") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;">'
            f'Privacy and security are our core principles. AayDocCapio operates entirely locally on your workstation. '
            f'Your clients\' PAN details, passwords, dates of birth, and downloaded financial statements are stored '
            f'strictly in an encrypted local database (vault) on your machine. No data is ever transmitted, '
            f'replicated, or stored on external cloud infrastructure. All automation actions occur directly between '
            f'your PC and the official government servers.</p>'
          )}
        </div>

        {_img("ADC_AppLandingPage", "AayDocCapio Main Desktop Application Interface", "App Landing Page")}
      </div>
    </section>

    <!-- SECTION 2: Getting Started -->
    <section id="getting-started">
      <div class="wrap">
        <div class="section-label">Section 2</div>
        <h2>Getting Started</h2>

        <div id="system-requirements" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("2.1. System Requirements") +
            bullets_html([
              '<strong>Operating System</strong>: Windows 10/11 (64-bit) recommended.',
              '<strong>Google Chrome</strong>: A standard, up-to-date Google Chrome installation is required. The app utilizes Playwright to automate Chrome in the background for securing AIS/TIS documents.',
              '<strong>Active Internet Connection</strong>: High-speed connection is recommended, as the app connects directly to official tax servers.',
            ]) +
            warn_box("Make sure your Google Chrome is functional and up-to-date. If Chrome is missing, the automation for AIS/TIS will fail.")
          )}
        </div>

        <div id="initial-setup" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("2.2. Setup Checklist") +
            steps_html([
              'Launch the application for the first time. The app will automatically initialize a local vault.',
              'Configure your preferred download destination folder under Settings.',
              'Ensure that Google Chrome is launched and updated to the latest version on your PC.',
            ])
          )}
        </div>
      </div>
    </section>

    <!-- SECTION 3: Managing Clients -->
    <section id="managing-clients">
      <div class="wrap">
        <div class="section-label">Section 3</div>
        <h2>Managing Clients</h2>

        <div id="client-profiles" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("3.1. Client Profiles") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Managing client credentials and details is fully centralized within the client registry. '
            f'You can access this through the <strong>Client Master</strong> menu on the top menu bar, or using the dashboard buttons.</p>'
            + steps_html([
              'Click the <strong>+ Add Client</strong> button on the toolbar or navigate to <strong>Client Master → Add Client</strong>.',
              'Enter the client\'s <strong>PAN</strong> (10 alphanumeric characters), <strong>Full Name</strong> (exactly as registered), '
              '<strong>Portal Password</strong>, and <strong>Date of Birth</strong> (DD-MM-YYYY format).',
              'Click <strong>Save</strong> to securely write this client to your encrypted local vault.'
            ])
          )}
          {_img("ADC_AddNewClient", "Add/Edit Client Details Dialog Screen", "Add New Client Dialog")}
          {_img("ADC_ClientMasterMenu", "Client Master dropdown menu actions", "Client Master Menu")}
        </div>

        <div id="importance-of-dob" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("3.2. Importance of Date of Birth (DOB)") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;">'
            f'Date of Birth is critical because it acts as the decryption key for secure documents. '
            f'The Income Tax Department encrypts Form 26AS ZIP archives using the DOB in {badge("DDMMYYYY")} format, '
            f'and AIS/TIS PDF files using a composite key of {badge("lowercase_pan + DDMMYYYY")}. '
            f'Without a correct DOB stored in the profile, the local decryption engine will be unable to unlock '
            f'and save the decrypted copies, leaving files password-protected.</p>'
          )}
        </div>

        <div id="bulk-import-export" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("3.3. Bulk Import & Export Client Data") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'For large practices, you can onboard multiple clients at once using our import templates:</p>'
            + steps_html([
              'Go to <strong>Client Master → Export Template</strong> to download a pre-formatted Excel template.',
              'Open the Excel file and fill out the client rows: <strong>PAN</strong>, <strong>Name</strong>, '
              '<strong>Password</strong>, and <strong>DOB (DD-MM-YYYY)</strong>.',
              'Import the filled Excel sheet using <strong>Client Master → Import Clients…</strong>.',
              'You can also export your current client list at any time to a spreadsheet using <strong>Client Master → Export Clients…</strong>.'
            ])
          )}
          {_img("ADC_ClientMasterMenu", "Client Master dropdown menu actions", "Client Master Menu")}
          {_img("ADC_SaveClientImportTemplate", "Saving the onboarding Excel template to disk", "Save Import Template")}
          {_img("ADC_ClientImportCompleteMessage", "Success confirmation showing imported records", "Client Import Success")}
        </div>
      </div>
    </section>

    <!-- SECTION 4: Bulk Download -->
    <section id="bulk-download">
      <div class="wrap">
        <div class="section-label">Section 4</div>
        <h2>Bulk Download</h2>

        <div id="select-clients-year" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("4.1. Selecting Clients and Year") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Before starting a download batch, configure the run parameters:</p>'
            + steps_html([
              'Check the checkbox next to the clients you want to process in the main dashboard grid.',
              'Use the top toolbar to choose the target <strong>Assessment Year</strong> (e.g. 2025-26).'
            ])
          )}
          {_img("ADC_YearSelector", "Setting the active Assessment Year", "Year Selector")}
        </div>

        <div id="bulk-26as-download" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("4.2. How to Initiate Bulk 26AS Download") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'To download Form 26AS for multiple clients:</p>'
            + steps_html([
              'Select target clients by checking their rows in the table.',
              'Under the <strong>Documents to Fetch</strong> checklist, ensure that <strong>26AS</strong> is checked.',
              'Click the primary <strong>Download</strong> button on the toolbar.',
              'The background automation will sequentially log in to each client\'s account, navigate to the TRACES portal, '
              'request 26AS in HTML/PDF and TXT format, download, and auto-decrypt the files.'
            ])
          )}
          {_img("ADC_26ASBatch", "Running Form 26AS download batch", "Form 26AS Batch Download")}
        </div>

        <div id="bulk-ais-download" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("4.3. How to Initiate Bulk AIS / TIS Download") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'To download AIS and TIS documents for multiple clients:</p>'
            + steps_html([
              'Select target clients by checking their rows in the table.',
              'Under <strong>Documents to Fetch</strong>, check <strong>AIS</strong> and/or <strong>TIS</strong>.',
              'Click the primary <strong>Download</strong> button on the toolbar.',
              'The background automation will log in, navigate to the Compliance Portal, download instantly available statements, '
              'or submit PDF generation requests for queued statements.'
            ])
          )}
          {_img("ADC_AISDownload", "Selecting AIS download options", "AIS Download Screen")}
        </div>

        <div id="menu-options-download" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("4.4. Which Menu / Toolbar Options to Click") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'In addition to checking boxes and clicking the main <strong>Download</strong> button, you can trigger specific runs directly via the menus:</p>'
            + bullets_html([
              '<strong>Main Toolbar "Download" Dropdown</strong>: Click the dropdown arrow next to the Download button to select '
              '<strong>Download Form 26AS Only</strong> or <strong>Download / Request TIS & AIS Only</strong>. This overrides '
              'the dashboard checkboxes and executes only that specific task.',
              '<strong>Right-Click Context Menu</strong>: Right-click any client row in the table and select <strong>Download Selected Clients...</strong>.'
            ])
          )}
          {_img("ADC_DownloadOptionsMenu", "Checking options and selecting target documents", "Download Options Menu")}
        </div>

        <div id="status-indicators" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("4.5. Status Indicators and Batch Control") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'A real-time progress dialog shows per-client status. Refer to the table below for icon meanings:</p>'
            f'<table class="data-table" style="margin-bottom:12px;">'
            f'<thead><tr><th style="width:60px;">Icon</th><th>Status</th><th>Meaning</th></tr></thead>'
            f'<tbody>{status_table_rows}</tbody>'
            f'</table>'
            + tip_box("You can stop a long-running batch at any time. Clicking the Stop button finishes the active client and safely skips the rest.")
          )}
          {_img("ADC_StatusBasedFilters", "Filtering client list based on download status", "Status Filters")}
        </div>
      </div>
    </section>

    <!-- SECTION 5: Form 26AS Details -->
    <section id="form-26as-details">
      <div class="wrap">
        <div class="section-label">Section 5</div>
        <h2>Form 26AS Details</h2>

        <div id="double-formats" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("5.1. HTML/PDF and TXT Formats") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Form 26AS is downloaded in two formats to maximize flexibility and usability:</p>'
            + bullets_html([
              '<strong>HTML/PDF Format</strong>: Provides a formatted, print-ready document containing the client\'s tax credits and details.',
              '<strong>TXT Format (ZIP)</strong>: Used for parsing and generating clean, parsed Excel files. This is downloaded directly from the TRACES portal.'
            ])
          )}
        </div>

        <div id="zip-extraction" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("5.2. ZIP Extraction and Decryption") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'The 26AS ZIP archive is locked by TRACES. The app automatically extracts the text file using the client\'s Date of Birth in {badge("DDMMYYYY")} format, '
            f'ensuring a completely seamless extraction without manual intervention.</p>'
          )}
          {_img("ADC_TracesPortal26ASDownloadScreen", "TRACES portal redirection screen for 26AS", "TRACES Download Screen")}
        </div>
      </div>
    </section>

    <!-- SECTION 6: AIS & TIS Details -->
    <section id="ais-tis-details">
      <div class="wrap">
        <div class="section-label">Section 6</div>
        <h2>AIS & TIS Details</h2>

        <div id="ais-tis-diffs" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("6.1. Key Differences") +
            bullets_html([
              '<strong>Annual Information Statement (AIS)</strong>: Contains comprehensive transaction data, including interest, mutual funds, stock trades, foreign remittances, and more.',
              '<strong>Taxpayer Information Summary (TIS)</strong>: A simplified summary document showing aggregated tax category values.',
            ])
          )}
        </div>

        <div id="two-phase-queue" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("6.2. Two-Phase Retrieval (Queue Mode)") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'The Income Tax Portal generates AIS PDFs on-demand, which can lead to two scenarios:</p>'
            + steps_html([
              '<strong>Phase 1: Instantly Available</strong>. If the portal already has a generated PDF, AayDocCapio retrieves and decrypts it immediately.',
              '<strong>Phase 2: Request Placed (Queued)</strong>. If a fresh PDF is required, the app submits a generation request. The status updates to a blue clock (🕐), meaning the request is queued.',
              '<strong>Subsequent Run</strong>. Re-run the client the next day. The app detects the ready PDF from the portal\'s Activity History and downloads it.',
            ]) +
            tip_box("TIS documents are always generated instantly and do not suffer from portal queue delays.")
          )}
          {_img("ADC_AISRequestPlaced", "AIS Request Placed - waiting for portal generation", "AIS Request Placed")}
          {_img("ADC_AISRequestResult", "Ready AIS PDF successfully retrieved on subsequent run", "AIS Request Result")}
        </div>
      </div>
    </section>

    <!-- SECTION 7: PDF Decryption -->
    <section id="pdf-decryption">
      <div class="wrap">
        <div class="section-label">Section 7</div>
        <h2>PDF Decryption</h2>

        <div id="decryption-rules" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("7.1. Decryption Rules") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Standard government downloads are protected by strong passwords. AayDocCapio incorporates an automatic '
            f'decryption system that removes these passwords before saving them to your folders.</p>'
            + bullets_html([
              'Attempts 9 password variations derived from the client\'s records.',
              f'AIS/TIS Password Rule: {badge("lowercase_pan + DDMMYYYY")} (e.g. {badge("aaapt0001a15081985")}).',
              f'26AS ZIP/PDF Password Rule: {badge("DDMMYYYY")} (e.g. {badge("15081985")}).',
              'Saves a fully unlocked, password-free version of the PDF for direct viewing, printing, or archiving.',
            ])
          )}
        </div>

        <div id="decryption-troubleshooting" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("7.2. Troubleshooting Decryption Failures") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;">'
            f'If the Date of Birth or PAN spelling is incorrect in your vault, the decryption engine will fail. '
            f'The app will leave the downloaded file intact in its password-locked state and flag the row with a yellow warning symbol (⚠️). '
            f'To resolve, simply verify the client\'s DOB against their actual PAN card, click Edit Client, update the details, and run the client again.</p>'
          )}
          {_img("ADC_ITDPortalPANLoginScreenWithError", "Interception of PAN login errors on the ITD portal", "PAN Login Error Interception")}
        </div>
      </div>
    </section>

    <!-- SECTION 8: Tools Menu Utilities -->
    <section id="tools-menu-section">
      <div class="wrap">
        <div class="section-label">Section 8</div>
        <h2>Tools Menu Utilities</h2>

        <div id="tools-26as" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("8.1. Convert 26AS TXT to Excel + HTML") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Translate raw TXT credit files into structured worksheets:</p>'
            + steps_html([
              'Go to <strong>Tools → Convert 26AS TXT to Excel + HTML…</strong>',
              'Select the raw <strong>.txt</strong> 26AS file from the client\'s output folder.',
              'Click Convert to output a beautifully formatted Excel workbook with separate sheets for each section, and a formatted HTML overview.'
            ])
          )}
          {_img("ADC_Select26AStxtFileForConversion", "Selecting raw 26AS text file for conversion", "Select 26AS text")}
          {_img("ADC_26ASConversionSuccessMessage", "Success alert after writing sheets and files", "26AS Success Message")}
        </div>

        <div id="tools-ais" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("8.2. Convert AIS JSON to Excel") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'AIS JSON files contain deep structured details. You can convert them to filterable Excel sheets:</p>'
            + steps_html([
              'Go to <strong>Tools → Convert AIS JSON → Excel…</strong>',
              'Select the raw <strong>AIS JSON</strong> file downloaded from the ITD portal.',
              'Confirm the output destination to generate a capital gains reconciliation sheet.'
            ])
          )}
          {_img("ADC_AISJsonSelectionScreen", "Selecting the raw AIS JSON file", "Select AIS JSON")}
          {_img("ADC_AISConversionSuccess", "AIS JSON conversion success dialog", "AIS Success Message")}
        </div>
      </div>
    </section>

    <!-- SECTION 9: Email Setup & Mailing -->
    <section id="email-setup-delivery">
      <div class="wrap">
        <div class="section-label">Section 9</div>
        <h2>Email Setup & Mailing</h2>

        <div id="how-to-setup-email" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("9.1. How to Setup Email (SMTP Configuration)") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'AayDocCapio allows you to email downloaded and decrypted tax documents directly to your clients '
            f'via SMTP. Setup takes just a few steps:</p>'
            + steps_html([
              'Go to <strong>Settings → Email Settings</strong> in the menu bar.',
              'Click on one of the **Provider Presets** (Gmail, Outlook, M365, Yahoo, iCloud) at the top of the dialog. This auto-populates host, port, and security settings.',
              'Fill in your **SMTP Username** (your full email address) and **SMTP Password** (see details below).',
              'Specify **CC** or **BCC** addresses if you want a copy sent to your backup inbox.',
              'Enter the **Sender Name** (your firm\'s name or your name) and select your preferred font/styling.',
              'Click **Send Test Email** to verify connection settings before proceeding.'
            ])
          )}
          {_img("ADC_EmailSMTPSettingsDialog", "SMTP credentials configuration panel", "Email SMTP Settings")}
        </div>

        <div id="email-settings-reference" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("9.2. Email Settings Reference") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Due to modern security standards, standard email account passwords are usually blocked for SMTP connections '
            f'if Multi-Factor Authentication (MFA) is active. Refer to the specific sub-sections below to configure your provider preset:</p>'
          )}
        </div>

        <div id="gmail-setup-ref" style="scroll-margin-top: 90px; margin-top: 16px; padding-left: 20px; border-left: 3px solid rgba(220,38,38,0.25);">
          {section_card(
            h3("9.2.1. Gmail & Google Workspace Configuration") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Google blocks traditional logins via simple passwords for security. To connect your Google inbox:</p>'
            + steps_html([
              'Enable <strong>2-Step Verification</strong> in your Google Account security settings.',
              'Go to <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener" style="color:#2563EB;">myaccount.google.com → Security → 2-Step Verification → App Passwords</a>.',
              'Select <strong>Mail</strong> as the app and <strong>Other</strong> or your custom name as the device, then click <strong>Generate</strong>.',
              'Copy the generated <strong>16-character password</strong> (e.g. <code>abcd efgh ijkl mnop</code>).',
              'Paste this App Password into the **SMTP Password** field in AayDocCapio (spaces are ignored).'
            ])
          )}
        </div>

        <div id="office365-setup-ref" style="scroll-margin-top: 90px; margin-top: 16px; padding-left: 20px; border-left: 3px solid rgba(216,59,1,0.25);">
          {section_card(
            h3("9.2.2. Microsoft 365 & Office 365 Setup") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'For Microsoft 365 / Outlook corporate accounts, standard security settings block SMTP authentication unless configured correctly:</p>'
            + bullets_html([
              '<strong>MFA / App Passwords</strong>: If Multi-Factor Authentication is enabled, sign in to <a href="https://mysignins.microsoft.com/security-info" target="_blank" rel="noopener" style="color:#2563EB;">mysignins.microsoft.com/security-info</a>, click **+ Add sign-in method**, choose **App password**, name it, and copy the password.',
              '<strong>Authenticated SMTP (Admin Center)</strong>: If the connection is refused, your organization\'s administrator must enable SMTP Auth for your account. Ask your IT admin to log in to the <a href="https://admin.microsoft.com" target="_blank" rel="noopener" style="color:#2563EB;">Microsoft 365 Admin Center</a> → Go to **Users → Active Users** → Click your user profile → Click **Mail** tab → Click **Manage email apps** → Ensure **Authenticated SMTP** is ticked and saved.'
            ])
          )}
        </div>

        <div id="yahoo-icloud-setup-ref" style="scroll-margin-top: 90px; margin-top: 16px; padding-left: 20px; border-left: 3px solid rgba(96,1,210,0.25);">
          {section_card(
            h3("9.2.3. Yahoo Mail & Apple iCloud Setup") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Both Yahoo and Apple iCloud require application-specific passwords to connect to SMTP servers:</p>'
            + bullets_html([
              '<strong>Yahoo Mail</strong>: Log in to your <a href="https://login.yahoo.com/account/security" target="_blank" rel="noopener" style="color:#2563EB;">Yahoo Account Security page</a>. Click **Generate app password**, choose **Other app** (name it AayDocCapio), copy the generated 16-character key, and paste it into the password field.',
              '<strong>Apple iCloud</strong>: Log in to <a href="https://appleid.apple.com" target="_blank" rel="noopener" style="color:#2563EB;">appleid.apple.com</a>. Navigate to **Sign-In and Security → App-Specific Passwords**, select **Generate**, name it, and copy the password to use in the SMTP Settings dialog.'
            ])
          )}
        </div>

        <div id="custom-exchange-ref" style="scroll-margin-top: 90px; margin-top: 16px; padding-left: 20px; border-left: 3px solid rgba(100,116,139,0.25);">
          {section_card(
            h3("9.2.4. Custom SMTP & Exchange Servers") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'If your firm uses on-premise MS Exchange or custom hosting (e.g., GoDaddy, Bluehost, Hostinger):</p>'
            + bullets_html([
              '<strong>Exchange SMTP Host</strong>: Typically formatted as <code>mail.yourdomain.com</code> or <code>smtp.yourdomain.com</code>. Contact your organization\'s system administrator to get the exact address.',
              '<strong>SMTP Port & Security</strong>: Use Port <code>587</code> with <code>STARTTLS</code> (recommended) or Port <code>465</code> with <code>SSL/TLS</code>. Standard unencrypted Port <code>25</code> is typically blocked by ISPs.',
              '<strong>Proxy & Firewall Restrictions</strong>: In corporate networks, ensure outgoing traffic on ports 587/465 is allowed by local network firewalls.'
            ]) +
            tip_box("Clicking any of the provider preset tiles in the Email Settings dialog displays a blue helper panel at the bottom with direct links to setup instructions.")
          )}
          {_img("ADC_TestMailSentConfirmation", "Test mail verification prompt", "Test Email success confirmation")}
        </div>

        <div id="automated-mailing" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("9.3. Mailing Converted/Downloaded Documents") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Once downloads complete, bulk send documents to clients in one click:</p>'
            + steps_html([
              'Click the **Email Docs** button on the main toolbar or go to **Tools → Mail Docs to Clients**.',
              'Select which documents to attach (e.g. Form 26AS PDF, 26AS Excel, AIS PDF, TIS PDF).',
              'Draft your email body. Use placeholder chips like `{client_name}`, `{pan}`, `{ay}`, and `{documents}`. '
              'The `{documents}` placeholder will automatically render as a bulleted list of the files attached.',
              'Click **Send** to launch the batch. Monitor sending progress live in the status grid.'
            ])
          )}
          {_img("ADC_EmailTemplateEditor", "Customizing email templates and subject lines", "Email Template Editor")}
          {_img("ADC_SendingBulMailstoClientsConfirmation", "Verification list prior to sending client emails", "Bulk email confirmation")}
          {_img("ADC_SendingBulMailstoClientsSuccess", "Bulk email delivery report", "Bulk email success status")}
          {_img("ADC_SampleMailSenttoClient", "Sample delivery layout received by client", "Sample email received")}
        </div>
      </div>
    </section>

    <!-- SECTION 10: Settings & Sub-sections -->
    <section id="settings-customization">
      <div class="wrap">
        <div class="section-label">Section 10</div>
        <h2>Settings & Sub-sections</h2>

        <div id="settings-folder" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("10.1. Download Folder Path") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Configure where files are saved. By default, they go to your standard Downloads folder.</p>'
            + steps_html([
              'Go to <strong>Settings → Download Folder</strong>.',
              'Browse and choose a target directory.',
              'Click OK. All future runs will automatically generate structured client sub-folders here.'
            ])
          )}
          {_img("ADC_SelectOutputDirectory", "Configuring the root download folder", "Select Output Directory")}
        </div>

        <div id="settings-ay" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("10.2. Manage Assessment Years") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'Add or remove financial periods to adapt to new tax cycles:</p>'
            + steps_html([
              'Go to <strong>Settings → Manage Assessment Years</strong>.',
              'Add a new year (e.g. AY 2026-27 / FY 2025-26) or delete older years.',
              'Reorder them to set the default year at startup.'
            ])
          )}
          {_img("ADC_ManageAssessmentYears", "Assessment year list management dialog", "Manage Assessment Years")}
        </div>

        <div id="settings-appearance" style="scroll-margin-top: 90px; margin-top: 24px;">
          {section_card(
            h3("10.3. Appearance & Themes") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;">'
            f'Switch between Light, Dark Navy, Slate, and Teal visual styles via <strong>Settings → Appearance</strong>. '
            f'Theme preference is saved locally and applies instantly on next application launch.</p>'
          )}
          {_img("ADC_SettingsMenu", "Global settings categories dropdown", "Settings Menu")}
        </div>
      </div>
    </section>

    <!-- SECTION 11: Software Updates -->
    <section id="app-updates">
      <div class="wrap">
        <div class="section-label">Section 11</div>
        <h2>Software Updates</h2>

        <div id="inbuilt-auto-update" style="scroll-margin-top: 90px; margin-top: 12px;">
          {section_card(
            h3("11.1. Inbuilt Update Checker") +
            f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
            f'AayDocCapio features an **inbuilt update checker** to ensure you are notified when new releases '
            f'are made available for compatibility with the ITD portal:</p>'
            + bullets_html([
              '<strong>Startup Check</strong>: On launch, the application automatically queries the release server in the background for newer versions.',
              '<strong>Blinking Update Alert</strong>: If an update is available, a blinking blue <strong>&#11015; vX.Y.Z available</strong> link is displayed next to the version details at the bottom of the main window. Clicking this link opens the official download page in your web browser.',
              '<strong>Manual Check</strong>: You can trigger an update check manually at any time by selecting <strong>Help → Check for Updates</strong> from the top menu bar.',
              '<strong>Manual Trigger Dialog</strong>: If a manual check detects an update, a confirmation dialog appears prompting you to open the download page. If the app is up to date, it displays an informational confirmation message.',
              '<strong>Installation</strong>: Once the download page (<code>https://download.aaydoccapio.com/</code>) opens, download the latest installer (e.g. <code>.exe</code> for Windows or <code>.zip</code> for macOS) and run it. The new installation automatically replaces the older version while safely keeping all your encrypted client profiles, history, and settings intact.'
            ])
          )}
          {_img("ADC_AutoUpdateBlinkingMessage", "Blinking update notification displayed under version details on the main dashboard", "Blinking update notification")}
          {_img("ADC_UpdateAvailable", "Update notification dialog shown on manual check (Help → Check for Updates)", "Update Available Dialog")}
        </div>
      </div>
    </section>

    <!-- SECTION 12: Troubleshooting & FAQ -->
    <section id="troubleshooting-faq">
      <div class="wrap">
        <div class="section-label">Section 12</div>
        <h2>Troubleshooting & FAQ</h2>
        
        <div id="error-resolutions" style="scroll-margin-top: 90px; margin-top: 12px;">
          <p style="color:#5A6B84;font-size:0.95rem;margin-bottom:24px;line-height:1.7;">
            Common error states, issues, and quick-fix procedures.
          </p>

          <div style="overflow-x:auto; margin-bottom:28px;">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Error / Status</th>
                  <th style="min-width:200px;">Cause</th>
                  <th style="min-width:220px;">Fix</th>
                </tr>
              </thead>
              <tbody>{prob_rows}</tbody>
            </table>
          </div>

          {_img("ADC_ErrorIfOutputSubFolderisNotYetCreated", "Error indicator shown when the target output path is missing or inaccessible", "Output path error")}
          {_img("ADC_ResumeButtonOnceDownloadisStoppedMidway", "Resume button in status column after stopping midway", "Resume button")}
        </div>

        <div id="faq-list" style="scroll-margin-top: 90px; margin-top: 24px;">
          <div class="section-label" style="margin-bottom:12px;">Frequently Asked Questions</div>
          {section_card(
            '<details>'
            '<summary>The batch is very slow — is this normal?</summary>'
            '<p>Yes. The app waits 5 seconds between clients to avoid triggering the ITD portal\'s rate-limit. '
            'For 50 clients downloading 26AS, expect 90–120 minutes total. Large batches (100+) are best run overnight.</p>'
            '</details>'
            '<details>'
            '<summary>Can I stop the batch midway?</summary>'
            '<p>Yes — click the <strong>Stop</strong> button in the progress dialog. Clients that already finished '
            'keep their status. Clients not yet started show ⏹ Skipped. Re-run only the remaining clients by '
            'selecting them individually.</p>'
            '</details>'
            '<details>'
            '<summary>The app shows a blank/white window on startup.</summary>'
            '<p>This is a display driver or WSL compositor glitch. Close the app and relaunch it. '
            'If it persists, restart your PC.</p>'
            '</details>'
            '<details>'
            '<summary>Antivirus flagged the installer — is it safe?</summary>'
            '<p>Yes. AayDocCapio uses Nuitka to compile Python to a native executable, which some antivirus '
            'engines flag as suspicious for unsigned code — this is a false positive. '
            'Click "More info" → "Run anyway" in Windows SmartScreen. The app only connects to the official '
            'ITD portal (eportal.incometax.gov.in) and Insight portal (ais.insight.gov.in).</p>'
            '</details>'
          )}
        </div>
      </div>
    </section>

  </main>
</div>

<!-- FOOTER -->
<div class="footer-strip">
  <strong>AayDocCapio</strong> &nbsp;•&nbsp; User Guide &nbsp;•&nbsp;
  <span style="opacity:0.6;">Close this tab to return to the app.</span>
</div>

<a href="#" class="floating-top" title="Back to Top">▲</a>

<script>
  (function() {{
    document.querySelectorAll('.info-card').forEach(function(card) {{
      card.addEventListener('mousemove', function(e) {{
        var rect = card.getBoundingClientRect();
        card.style.setProperty('--mouse-x', ((e.clientX - rect.left) / rect.width * 100).toFixed(1) + '%');
        card.style.setProperty('--mouse-y', ((e.clientY - rect.top) / rect.height * 100).toFixed(1) + '%');
      }});
    }});

    // Scrollspy logic
    const heroTitle = document.getElementById('hero-title');
    const navBrand = document.querySelector('.nav-brand');
    const targets = document.querySelectorAll('.content-area [id]');
    const navItems = document.querySelectorAll('.sidebar-nav-item');

    function updateActiveNavItem() {{
      let currentId = '';
      const scrollPosition = window.scrollY + 100;

      targets.forEach(target => {{
        const top = target.offsetTop;
        if (scrollPosition >= top - 20) {{
          currentId = target.getAttribute('id');
        }}
      }});

      if (!currentId && targets.length > 0) {{
        currentId = targets[0].getAttribute('id');
      }}

      // Clear all active states on groups
      document.querySelectorAll('.sidebar-group').forEach(group => {{
        group.classList.remove('active');
      }});

      // Update active state on nav items
      navItems.forEach(item => {{
        item.classList.remove('active');
        if (item.getAttribute('href') === '#' + currentId) {{
          item.classList.add('active');
          // Add active class to the parent group so its sub-items expand
          const group = item.closest('.sidebar-group');
          if (group) {{
            group.classList.add('active');
          }}
        }}
      }});

      // Dynamic Sticky Header Text change
      if (heroTitle && navBrand) {{
        const rect = heroTitle.getBoundingClientRect();
        if (rect.bottom <= 0) {{
          if (navBrand.innerHTML !== 'AayDocCapio Help Center') {{
            navBrand.innerHTML = 'AayDocCapio Help Center';
          }}
        }} else {{
          if (navBrand.innerHTML !== 'AayDoc <span style="color:#B88924;">Capio</span>™') {{
            navBrand.innerHTML = 'AayDoc <span style="color:#B88924;">Capio</span>™';
          }}
        }}
      }}
    }}

    window.addEventListener('scroll', updateActiveNavItem);
    window.addEventListener('resize', updateActiveNavItem);
    updateActiveNavItem();
  }})();
</script>
</body>
</html>"""


def _write_user_manual_html() -> str:
    """Generate the user help manual, write to a temp file, return the file path."""
    import base64 as _b64mod, tempfile
    from config import _bundled_dir

    def _b64(rel: str) -> str:
        p = os.path.join(_bundled_dir(), rel)
        if not os.path.isfile(p):
            return ""
        with open(p, "rb") as f:
            data = _b64mod.b64encode(f.read()).decode()
        ext = os.path.splitext(rel)[1].lower().lstrip(".")
        mime = "png" if ext == "png" else "jpeg" if ext in ("jpg", "jpeg") else "png"
        return f"data:image/{mime};base64,{data}"

    screenshots_dir = "Documentation/screenshots"
    img_uris = {
        "ADC_26ASBatch":                           _b64(f"{screenshots_dir}/ADC_26ASBatch.png"),
        "ADC_Aboutus":                             _b64(f"{screenshots_dir}/ADC_Aboutus.png"),
        "ADC_AddNewClient":                        _b64(f"{screenshots_dir}/ADC_AddNewClient.png"),
        "ADC_AppLandingPage":                      _b64(f"{screenshots_dir}/ADC_AppLandingPage.png"),
        "ADC_ClientImportCompleteMessage":         _b64(f"{screenshots_dir}/ADC_ClientImportCompleteMessage.png"),
        "ADC_ClientMasterMenu":                    _b64(f"{screenshots_dir}/ADC_ClientMasterMenu.png"),
        "ADC_DownloadOptionsMenu":                 _b64(f"{screenshots_dir}/ADC_DownloadOptionsMenu.png"),
        "ADC_EmailSMTPSettingsDialog":             _b64(f"{screenshots_dir}/ADC_EmailSMTPSettingsDialog.png"),
        "ADC_EmailTemplateEditor":                 _b64(f"{screenshots_dir}/ADC_EmailTemplateEditor.png"),
        "ADC_ErrorIfOutputSubFolderisNotYetCreated": _b64(f"{screenshots_dir}/ADC_ErrorIfOutputSubFolderisNotYetCreated.png"),
        "ADC_HelpMenu":                            _b64(f"{screenshots_dir}/ADC_HelpMenu.png"),
        "ADC_ITDPortalDashboardPostLogin":         _b64(f"{screenshots_dir}/ADC_ITDPortalDashboardPostLogin.png"),
        "ADC_ITDPortalPANLoginScreenWithError":    _b64(f"{screenshots_dir}/ADC_ITDPortalPANLoginScreenWithError.png"),
        "ADC_ITDPortalPasswordInputScreen":        _b64(f"{screenshots_dir}/ADC_ITDPortalPasswordInputScreen.png"),
        "ADC_LoginFailedDuetoIncorrectPANerror":   _b64(f"{screenshots_dir}/ADC_LoginFailedDuetoIncorrectPANerror.png"),
        "ADC_ManageAssessmentYears":               _b64(f"{screenshots_dir}/ADC_ManageAssessmentYears.png"),
        "ADC_OutPutFolderScreenshot":              _b64(f"{screenshots_dir}/ADC_OutPutFolderScreenshot.png"),
        "ADC_ResumeButtonOnceDownloadisStoppedMidway": _b64(f"{screenshots_dir}/ADC_ResumeButtonOnceDownloadisStoppedMidway.png"),
        "ADC_SampleMailSenttoClient":              _b64(f"{screenshots_dir}/ADC_SampleMailSenttoClient.png"),
        "ADC_SaveClientImportTemplate":            _b64(f"{screenshots_dir}/ADC_SaveClientImportTemplate.png"),
        "ADC_Select26AStxtFileForConversion":      _b64(f"{screenshots_dir}/ADC_Select26AStxtFileForConversion.png"),
        "ADC_SelectOutputDirectory":               _b64(f"{screenshots_dir}/ADC_SelectOutputDirectory.png"),
        "ADC_SendingBulMailstoClientsConfirmation": _b64(f"{screenshots_dir}/ADC_SendingBulMailstoClientsConfirmation.png"),
        "ADC_SendingBulMailstoClientsSuccess":      _b64(f"{screenshots_dir}/ADC_SendingBulMailstoClientsSuccess.png"),
        "ADC_SettingsMenu":                        _b64(f"{screenshots_dir}/ADC_SettingsMenu.png"),
        "ADC_StatusBasedFilters":                  _b64(f"{screenshots_dir}/ADC_StatusBasedFilters.png"),
        "ADC_TestMailSentConfirmation":            _b64(f"{screenshots_dir}/ADC_TestMailSentConfirmation.png"),
        "ADC_ToolsMenu":                           _b64(f"{screenshots_dir}/ADC_ToolsMenu.png"),
        "ADC_TracesPortal26ASDownloadScreen":      _b64(f"{screenshots_dir}/ADC_TracesPortal26ASDownloadScreen.png"),
        "ADC_UpdateAvailable":                     _b64(f"{screenshots_dir}/ADC_UpdateAvailable.png"),
        "ADC_YearSelector":                        _b64(f"{screenshots_dir}/ADC_YearSelector.png"),
        "ADC_26ASConversionSuccessMessage":        _b64(f"{screenshots_dir}/ADC_26ASConversionSuccessMessage.png"),
        "ADC_AISConversionCredentialinputScreen":   _b64(f"{screenshots_dir}/ADC_AISConversionCredentialinputScreen.png"),
        "ADC_AISConversionSuccess":                _b64(f"{screenshots_dir}/ADC_AISConversionSuccess.png"),
        "ADC_AISJsonSelectionScreen":              _b64(f"{screenshots_dir}/ADC_AISJsonSelectionScreen.png"),
        "ADC_AbortActiveDowloadConfirmationDialog": _b64(f"{screenshots_dir}/ADC_AbortActiveDowloadConfirmationDialog.png"),
        "ADC_AISDownload":                         _b64(f"{screenshots_dir}/ADC_AISDownload.png"),
        "ADC_AISRequestPlaced":                    _b64(f"{screenshots_dir}/ADC_AISRequestPlaced.png"),
        "ADC_AISRequestResult":                    _b64(f"{screenshots_dir}/ADC_AISRequestResult.png"),
        "ADC_AutoUpdateBlinkingMessage":           _b64(f"{screenshots_dir}/ADC_AutoUpdateBlinkingMessage.png"),
    }

    html = _user_manual_page_html(img_uris)
    out = os.path.join(tempfile.gettempdir(), "aay_user_manual.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out
