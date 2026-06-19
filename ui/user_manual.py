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
  <h1>AayDocCapio Help Center</h1>
  <p>Your comprehensive self-service guide for automated bulk retrieval of tax documents from the ITD portal.</p>
</div>

<!-- MAIN LAYOUT -->
<div class="main-layout">
  <!-- SIDEBAR NAVIGATOR -->
  <aside class="sidebar">
    <div class="sidebar-nav">
      <a href="#overview" class="sidebar-nav-item active">1. Overview</a>
      <a href="#getting-started" class="sidebar-nav-item">2. Getting Started</a>
      <a href="#client-vault" class="sidebar-nav-item">3. Client Vault</a>
      <a href="#bulk-download" class="sidebar-nav-item">4. Bulk Download</a>
      <a href="#form-26as" class="sidebar-nav-item">5. Form 26AS</a>
      <a href="#ais-tis" class="sidebar-nav-item">6. AIS & TIS</a>
      <a href="#pdf-unlock" class="sidebar-nav-item">7. PDF Decryption</a>
      <a href="#import-export" class="sidebar-nav-item">8. Import / Export</a>
      <a href="#tools-menu" class="sidebar-nav-item">9. Tools Menu</a>
      <a href="#mail-docs" class="sidebar-nav-item">10. Mail to Clients</a>
      <a href="#settings-themes" class="sidebar-nav-item">11. Settings & Themes</a>
      <a href="#check-updates" class="sidebar-nav-item">12. Check for Updates</a>
      <a href="#faq-troubleshooting" class="sidebar-nav-item">13. Troubleshooting & FAQ</a>
    </div>
  </aside>

  <!-- MAIN CONTENT AREA -->
  <main class="content-area">

    <!-- SECTION 1: Overview -->
    <section id="overview">
      <div class="wrap">
        <div class="section-label">Section 1</div>
        <h2>Overview</h2>
        
        {section_card(
          h3("What is AayDocCapio?") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'AayDocCapio is a powerful desktop application built specifically for Chartered Accountants (CAs), '
          f'tax practitioners, and financial auditors. It automates the tedious, repetitive process of logging into '
          f'the Income Tax Department (ITD) portal to retrieve key tax compliance documents for multiple clients.</p>'
          + bullets_html([
            '<strong>Bulk Automation</strong>: Replaces hours of manual login, navigation, and file downloading with a single click.',
            '<strong>Supported Statements</strong>: Fetches Form 26AS (TXT + PDF), Annual Information Statement (AIS PDF + JSON), and Taxpayer Information Summary (TIS PDF).',
            '<strong>Local Decryption</strong>: Automatically decrypts downloaded files, delivering clean, password-free documents to your output folders.',
          ])
        )}

        {section_card(
          h3("No-Cloud Privacy Guarantee") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;">'
          f'Privacy and security are our core principles. AayDocCapio operates entirely locally on your workstation. '
          f'Your clients\' PAN details, passwords, dates of birth, and downloaded financial statements are stored '
          f'strictly in an encrypted local database (vault) on your machine. No data is ever transmitted, '
          f'replicated, or stored on external cloud infrastructure. All automation actions occur directly between '
          f'your PC and the official government servers.</p>'
        )}

        {_img("ADC_AppLandingPage", "AayDocCapio Main Desktop Application Interface", "App Landing Page")}
      </div>
    </section>

    <!-- SECTION 2: Getting Started -->
    <section id="getting-started">
      <div class="wrap">
        <div class="section-label">Section 2</div>
        <h2>Getting Started</h2>

        {section_card(
          h3("System Requirements") +
          bullets_html([
            '<strong>Operating System</strong>: Windows 10/11 (64-bit) recommended.',
            '<strong>Google Chrome</strong>: A standard, up-to-date Google Chrome installation is required. The app utilizes Playwright to automate Chrome in the background for securing AIS/TIS documents.',
            '<strong>Active Internet Connection</strong>: High-speed connection is recommended, as the app connects directly to official tax servers.',
          ]) +
          warn_box("Make sure your Google Chrome is functional and up-to-date. If Chrome is missing, the automation for AIS/TIS will fail.")
        )}

        {section_card(
          h3("Initial Setup Checklist") +
          steps_html([
            'Launch the application for the first time. The app will automatically initialize a local vault.',
            'Configure your preferred download destination folder under Settings.',
            'Ensure that Google Chrome is launched and updated to the latest version on your PC.',
          ])
        )}

        {section_card(
          h3("Specifying the Download Folder") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'All downloads are organized systematically. You can select the root folder under <strong>Settings → Download Folder</strong>. '
          f'From that root, the app generates individual folders for each client, categorized by year:</p>'
          f'<code style="background:rgba(10,22,40,0.06);display:block;padding:12px;border-radius:8px;font-family:monospace;font-size:0.85rem;margin-bottom:12px;">'
          f'[Your Selected Folder] / [Client Name]_[PAN] / [Assessment Year] /</code>'
          + tip_box("The default folder is your standard Windows 'Downloads' directory. You can redirect this to a secure file server or workspace folder.")
        )}

        {_img("ADC_SelectOutputDirectory", "Configuring the root download folder", "Select Output Directory")}
        {_img("ADC_OutPutFolderScreenshot", "Systematic folder organization of downloaded files", "Output Folder Structure")}
      </div>
    </section>

    <!-- SECTION 3: Client Vault -->
    <section id="client-vault">
      <div class="wrap">
        <div class="section-label">Section 3</div>
        <h2>Client Vault</h2>

        {section_card(
          h3("Managing Client Profiles") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'The Client Vault is your local address book. Access it through the Client Master menu or the main view dashboard.</p>'
          + steps_html([
            'Click <strong>+ Add Client</strong> or navigate to <strong>Client Master → Add Client</strong>.',
            'Enter the client\'s <strong>PAN</strong> (10 alphanumeric characters), <strong>Full Name</strong> (as per PAN database), <strong>Portal Password</strong>, and <strong>Date of Birth</strong> (DD-MM-YYYY format).',
            'Click <strong>Save</strong> to commit to the local database.',
          ])
        )}

        {_img("ADC_AddNewClient", "Add/Edit Client Details Dialog Screen", "Add New Client Dialog")}

        {section_card(
          h3("Why is Date of Birth (DOB) Crucial?") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;">'
          f'The DOB is not just for profile completeness; it is the cryptographic key needed to unlock '
          f'downloaded tax statements. Form 26AS ZIP files are password-protected using DOB in {badge("DDMMYYYY")} format, '
          f'and AIS/TIS PDF files use a composite key of {badge("lowercase_pan + DDMMYYYY")}. Without the correct DOB, '
          f'the local decryption engine will fail, leaving the files locked in their raw government-issued format.</p>'
        )}

        {_img("ADC_ClientMasterMenu", "Client Master dropdown menu actions", "Client Master Menu")}
      </div>
    </section>

    <!-- SECTION 4: Bulk Download -->
    <section id="bulk-download">
      <div class="wrap">
        <div class="section-label">Section 4</div>
        <h2>Bulk Download</h2>

        {section_card(
          h3("Running a Batch Download") +
          steps_html([
            'Select the clients you want to run by checking the box next to their names in the main table.',
            'Select the target <strong>Assessment Year</strong> from the toolbar dropdown.',
            'Select the document types to fetch: <strong>26AS</strong>, <strong>AIS</strong>, and/or <strong>TIS</strong>.',
            'Click the primary <strong>Run Download</strong> button to start the execution.',
            'A real-time progress dialog will pop up showing the current client, document sub-task status, and active step.',
          ])
        )}

        {_img("ADC_DownloadOptionsMenu", "Checking options and selecting target documents", "Download Options Menu")}
        {_img("ADC_YearSelector", "Setting the active Assessment Year", "Year Selector")}

        {section_card(
          h3("Status Indicators and Batch Control") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'Each client row updates live with icons representing their document status. Refer to the table below:</p>'
          f'<table class="data-table" style="margin-bottom:12px;">'
          f'<thead><tr><th style="width:60px;">Icon</th><th>Status</th><th>Meaning</th></tr></thead>'
          f'<tbody>{status_table_rows}</tbody>'
          f'</table>'
          + tip_box("You can stop a long-running batch at any time. Clicking the Stop button finishes the active client and safely skips the rest.")
        )}

        {_img("ADC_StatusBasedFilters", "Filtering client list based on download status", "Status Filters")}
      </div>
    </section>

    <!-- SECTION 5: Form 26AS -->
    <section id="form-26as">
      <div class="wrap">
        <div class="section-label">Section 5</div>
        <h2>Form 26AS</h2>

        {section_card(
          h3("Understanding Form 26AS Downloads") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'Form 26AS is the Tax Credit Statement showing details of tax deducted, tax collected, and advance tax payments.</p>'
          + bullets_html([
            f'<strong>Double Output Formats</strong>: The app fetches 26AS in both <strong>HTML/PDF</strong> and raw <strong>TXT (ZIP format)</strong>.',
            f'<strong>Automatic Unzipping</strong>: The ZIP archive containing the TXT is automatically unpacked using the client\'s {badge("DDMMYYYY")} DOB password.',
            f'<strong>Reconciliation Ready</strong>: The extracted TXT file is saved in the output directory and is ready to be converted into an audit-friendly Excel sheet.',
          ])
        )}

        {_img("ADC_TracesPortal26ASDownloadScreen", "TRACES portal redirection screen for 26AS", "TRACES Download Screen")}
      </div>
    </section>

    <!-- SECTION 6: AIS & TIS -->
    <section id="ais-tis">
      <div class="wrap">
        <div class="section-label">Section 6</div>
        <h2>AIS & TIS</h2>

        {section_card(
          h3("AIS and TIS Differences") +
          bullets_html([
            '<strong>Annual Information Statement (AIS)</strong>: Contains comprehensive transaction data, including interest, mutual funds, stock trades, foreign remittances, and more.',
            '<strong>Taxpayer Information Summary (TIS)</strong>: A simplified summary document showing aggregated tax category values.',
          ])
        )}

        {section_card(
          h3("The Two-Phase Retrieval (Queued Requests)") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'The Income Tax Portal generates AIS PDFs on-demand, which can lead to two scenarios:</p>'
          + steps_html([
            '<strong>Phase 1: Instantly Available</strong>. If the portal already has a generated PDF, AayDocCapio retrieves and decrypts it immediately.',
            '<strong>Phase 2: Request Placed (Queued)</strong>. If a fresh PDF is required, the app submits a generation request. The status updates to a blue clock (🕐), meaning the request is queued.',
            '<strong>Subsequent Run</strong>. Re-run the client the next day. The app detects the ready PDF from the portal\'s Activity History and downloads it.',
          ]) +
          tip_box("TIS documents are always generated instantly and do not suffer from portal queue delays.")
        )}

        {_img("ADC_AISDownload", "Selecting AIS download options", "AIS Download Screen")}
        {_img("ADC_AISRequestPlaced", "AIS Request Placed - waiting for portal generation", "AIS Request Placed")}
        {_img("ADC_AISRequestResult", "Ready AIS PDF successfully retrieved on subsequent run", "AIS Request Result")}
      </div>
    </section>

    <!-- SECTION 7: PDF Decryption -->
    <section id="pdf-unlock">
      <div class="wrap">
        <div class="section-label">Section 7</div>
        <h2>PDF Decryption</h2>

        {section_card(
          h3("How Decryption Works") +
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

        {section_card(
          h3("What happens if decryption fails?") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;">'
          f'If the Date of Birth or PAN spelling is incorrect in your vault, the decryption engine will fail. '
          f'The app will leave the downloaded file intact in its password-locked state and flag the row with a yellow warning symbol (⚠️). '
          f'To resolve, simply verify the client\'s DOB against their actual PAN card, click Edit Client, update the details, and run the client again.</p>'
        )}

        {_img("ADC_ITDPortalPANLoginScreenWithError", "Interception of PAN login errors on the ITD portal", "PAN Login Error Interception")}
        {_img("ADC_LoginFailedDuetoIncorrectPANerror", "Invalid PAN error indication from portal", "Incorrect PAN Error")}
      </div>
    </section>

    <!-- SECTION 8: Import / Export -->
    <section id="import-export">
      <div class="wrap">
        <div class="section-label">Section 8</div>
        <h2>Import / Export</h2>

        {section_card(
          h3("Bulk Onboarding Clients") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'Manually adding clients one by one can be slow. AayDocCapio supports Excel-based bulk import and export.</p>'
          + steps_html([
            'Export a clean formatting template by clicking <strong>Client Master → Export Template</strong>.',
            'Open the Excel template and fill in the columns: <strong>PAN</strong>, <strong>Full Name</strong>, <strong>Portal Password</strong>, and <strong>Date of Birth (DD-MM-YYYY)</strong>.',
            'Save the spreadsheet and import it back into the app using <strong>Client Master → Import Clients…</strong>.',
            'Review the import summary dialog containing counts of added, updated, and error rows.',
          ])
        )}

        {_img("ADC_SaveClientImportTemplate", "Saving the onboarding Excel template to disk", "Save Import Template")}
        {_img("ADC_ClientImportCompleteMessage", "Success confirmation showing imported records", "Client Import Success")}
      </div>
    </section>

    <!-- SECTION 9: Tools Menu -->
    <section id="tools-menu">
      <div class="wrap">
        <div class="section-label">Section 9</div>
        <h2>Tools Menu</h2>

        {section_card(
          h3("Conversion Utilities") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'AayDocCapio includes offline processing utilities under the Tools menu to translate raw files into structured spreadsheets.</p>'
          + bullets_html([
            '<strong>26AS TXT Converter</strong>: Converts the raw, unzipped 26AS TXT file into a structured Excel workbook (.xlsx) containing an overview sheet and section tabs, plus a formatted HTML summary file.',
            '<strong>AIS JSON Converter</strong>: Converts the raw AIS JSON data into an organized multi-sheet Excel workbook. It organizes capital gains, salary, dividends, and interest into clear, filterable tables.',
          ])
        )}

        {_img("ADC_ToolsMenu", "Utility actions in the main menu bar", "Tools Menu")}

        {section_card(
          h3("Running the 26AS Conversion") +
          steps_html([
            'Go to <strong>Tools → Convert 26AS TXT → Excel + HTML…</strong>',
            'Browse and select the <strong>.txt</strong> 26AS file from the client\'s output folder.',
            'Select the target directory and click Convert.',
          ])
        )}

        {_img("ADC_Select26AStxtFileForConversion", "Selecting raw 26AS text file for conversion", "Select 26AS text")}
        {_img("ADC_26ASConversionSuccessMessage", "Success alert after writing sheets and files", "26AS Success Message")}

        {section_card(
          h3("Running the AIS JSON Conversion") +
          steps_html([
            'Go to <strong>Tools → Convert AIS JSON → Excel…</strong>',
            'Select the raw <strong>AIS JSON</strong> file downloaded from the ITD portal.',
            'Set output location and confirm the conversion to build a comprehensive capital gains workbook.',
          ])
        )}

        {_img("ADC_AISJsonSelectionScreen", "Selecting the raw AIS JSON file", "Select AIS JSON")}
        {_img("ADC_AISConversionSuccess", "AIS JSON conversion success dialog", "AIS Success Message")}
      </div>
    </section>

    <!-- SECTION 10: Mail Docs to Clients -->
    <section id="mail-docs">
      <div class="wrap">
        <div class="section-label">Section 10</div>
        <h2>Mail Docs to Clients</h2>

        {section_card(
          h3("Automated Client Emailing") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'Directly deliver retrieved tax files to clients without copying files or switching to an email app.</p>'
          + steps_html([
            'Setup SMTP mail client parameters under Settings.',
            'Go to the main client table, select the target clients, and click the <strong>Email Documents</strong> button.',
            'Choose the files you wish to attach (unlocked PDFs, converted Excel sheets).',
            'Review the email template, customize the text, and click Send.',
          ])
        )}

        {_img("ADC_EmailSMTPSettingsDialog", "SMTP credentials configuration panel", "Email SMTP Settings")}
        {_img("ADC_EmailTemplateEditor", "Customizing email templates and subject lines", "Email Template Editor")}

        {section_card(
          h3("SMTP Configuration and Providers") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'Configure server parameters, ports, and secure connections. Predefined presets are included for Gmail, Office 365, Outlook.com, and Yahoo.</p>'
          + bullets_html([
            '<strong>Port 587 (STARTTLS)</strong>: Standard secure connection for modern mail servers.',
            '<strong>Gmail App Passwords</strong>: If using Gmail, you must generate a 16-character App Password under your Google Account Security settings.',
            '<strong>Test Connection</strong>: Use the "Send Test Email" utility inside the dialog to verify SMTP server handshake before running batch emails.',
          ])
        )}

        {_img("ADC_TestMailSentConfirmation", "Test mail verification prompt", "Test Email success confirmation")}
        {_img("ADC_SendingBulMailstoClientsConfirmation", "Verification list prior to sending client emails", "Bulk email confirmation")}
        {_img("ADC_SendingBulMailstoClientsSuccess", "Bulk email delivery report", "Bulk email success status")}
        {_img("ADC_SampleMailSenttoClient", "Sample delivery layout received by client", "Sample email received")}
      </div>
    </section>

    <!-- SECTION 11: Settings & Themes -->
    <section id="settings-themes">
      <div class="wrap">
        <div class="section-label">Section 11</div>
        <h2>Settings & Themes</h2>

        {section_card(
          h3("Configuring Assessment Years") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'AayDocCapio updates dynamically to accommodate new tax periods. Manage years via the Settings menu.</p>'
          + steps_html([
            'Navigate to <strong>Settings → Manage Assessment Years</strong>.',
            'Add a new year (e.g. 2025-26) or delete old, inactive assessment periods.',
            'These settings update the toolbar selectors and download path mapping instantly.',
          ])
        )}

        {_img("ADC_SettingsMenu", "Global settings categories dropdown", "Settings Menu")}
        {_img("ADC_ManageAssessmentYears", "Assessment year list management dialog", "Manage Assessment Years")}

        {section_card(
          h3("Visual Themes") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;">'
          f'Reduce eye strain during tax season by tailoring the interface. Change themes from <strong>Settings → Appearance</strong>. '
          f'Options include: Light theme (clean, bright office look), Dark Navy (deep blue contrast), Slate, and Teal. '
          f'Your theme choice is stored in your preferences and persists across app restarts.</p>'
        )}
      </div>
    </section>

    <!-- SECTION 12: Check for Updates -->
    <section id="check-updates">
      <div class="wrap">
        <div class="section-label">Section 12</div>
        <h2>Check for Updates</h2>

        {section_card(
          h3("Keeping AayDocCapio Updated") +
          f'<p style="color:#1A2233;font-size:0.95rem;line-height:1.7;margin-bottom:12px;">'
          f'As the ITD portal updates its code, login fields, and security checks, AayDocCapio receives frequent releases to preserve automation compatibility.</p>'
          + steps_html([
            'Go to <strong>Help → Check for Updates</strong> in the menu bar.',
            'The application queries the release repository for new versions.',
            'If a new version is detected, a dialog detailing the changelog and release notes will appear, along with a download link.',
          ])
        )}

        {_img("ADC_UpdateAvailable", "New version detected and changelog notification", "Update Available Dialog")}
      </div>
    </section>

    <!-- SECTION 13: FAQ & Troubleshooting -->
    <section id="faq-troubleshooting">
      <div class="wrap">
        <div class="section-label">Section 13</div>
        <h2>FAQ & Troubleshooting</h2>
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

        <div style="margin-top:28px;">
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
    const sections = document.querySelectorAll('.content-area section');
    const navItems = document.querySelectorAll('.sidebar-nav-item');

    function updateActiveNavItem() {{
      let currentSectionId = '';
      const scrollPosition = window.scrollY + 100; // offset for sticky navbar

      sections.forEach(section => {{
        const top = section.offsetTop;
        const height = section.offsetHeight;
        if (scrollPosition >= top && scrollPosition < top + height) {{
          currentSectionId = section.getAttribute('id');
        }}
      }});

      if (window.scrollY < 200) {{
        currentSectionId = 'overview';
      }}

      navItems.forEach(item => {{
        item.classList.remove('active');
        if (item.getAttribute('href') === '#' + currentSectionId) {{
          item.classList.add('active');
        }}
      }});
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
    }

    html = _user_manual_page_html(img_uris)
    out = os.path.join(tempfile.gettempdir(), "aay_user_manual.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out
