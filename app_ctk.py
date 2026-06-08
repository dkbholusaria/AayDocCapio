import os
import sys
import json
import asyncio
import threading
import pandas as pd
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Append current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from vault import VaultManager
from automation.browser import browser_manager
from automation.auth import login_itd, logout_itd
from automation.downloader_26as import download_26as
from automation.downloader_ais_tis import download_ais_tis

# Set Modern Appearance - default to Light mode as requested
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

def get_timestamp():
    import datetime
    try:
        from zoneinfo import ZoneInfo
        local_now = datetime.datetime.now(ZoneInfo('Asia/Kolkata'))
    except Exception:
        local_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    return local_now.strftime('%d-%m-%Y %H:%M:%S')

class ManageYearsDialog(ctk.CTkToplevel):
    """Modal dialog to view, enable/disable, and add Assessment / Tax Year entries."""

    def __init__(self, parent, json_path: str, on_save):
        super().__init__(parent)
        self.title("Manage Assessment / Tax Years")
        self.geometry("520x560")
        self.resizable(False, False)

        self._json_path = json_path
        self._on_save = on_save
        self._entry_rows = []   # list of [entry_dict, BooleanVar]

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

        self._build_ui(entries)

        # Delay grab so widgets fully render before locking focus
        self.after(150, self._activate)

    def _activate(self):
        self.grab_set()
        self.lift()
        self.focus_force()

    def _build_ui(self, entries):
        ctk.CTkLabel(self, text="Manage Assessment / Tax Years",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(15, 2))
        ctk.CTkLabel(self, text="Toggle enabled/disabled or add new years.",
                     font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(pady=(0, 10))

        # ── Existing entries ──────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Existing Entries", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(0, 4))

        self._list_frame = ctk.CTkScrollableFrame(self, height=180)
        self._list_frame.pack(fill="x", padx=15, pady=(0, 5))

        for e in entries:
            self._add_row_widget(e)

        ctk.CTkFrame(self, height=1, fg_color=("#E2E8F0", "#334155")).pack(fill="x", padx=15, pady=8)

        # ── Add new year form ─────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Add New Year", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(0, 6))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=20)

        # Type row
        r1 = ctk.CTkFrame(form, fg_color="transparent")
        r1.pack(fill="x", pady=3)
        ctk.CTkLabel(r1, text="Type:", width=45, anchor="w").pack(side="left")
        self._type_var = ctk.StringVar(value="AY")
        ctk.CTkRadioButton(r1, text="AY (Assessment Year)", variable=self._type_var, value="AY",
                           command=self._auto_fy).pack(side="left", padx=(8, 20))
        ctk.CTkRadioButton(r1, text="TY (Tax Year)", variable=self._type_var, value="TY",
                           command=self._auto_fy).pack(side="left")

        # Year + FY row
        r2 = ctk.CTkFrame(form, fg_color="transparent")
        r2.pack(fill="x", pady=3)
        ctk.CTkLabel(r2, text="Year:", width=45, anchor="w").pack(side="left")
        self._year_entry = ctk.CTkEntry(r2, placeholder_text="e.g. 2027-28", width=115,
                                        fg_color=("#FFFFFF", "#1F2937"))
        self._year_entry.pack(side="left", padx=(8, 20))
        ctk.CTkLabel(r2, text="FY:", width=25, anchor="w").pack(side="left")
        self._fy_entry = ctk.CTkEntry(r2, placeholder_text="auto-filled", width=115,
                                      fg_color=("#FFFFFF", "#1F2937"))
        self._fy_entry.pack(side="left", padx=8)
        ctk.CTkLabel(r2, text="(editable)", font=ctk.CTkFont(size=10),
                     text_color=("#94A3B8", "#64748B")).pack(side="left")

        self._year_entry.bind("<KeyRelease>", lambda _: self._auto_fy())

        ctk.CTkButton(form, text="＋ Add to List", command=self._add_entry,
                      height=32, width=130).pack(anchor="w", pady=(10, 0))

        ctk.CTkFrame(self, height=1, fg_color=("#E2E8F0", "#334155")).pack(fill="x", padx=15, pady=8)

        # ── Bottom buttons ────────────────────────────────────────────────────
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkButton(btns, text="💾 Save & Close", height=36,
                      fg_color=("#2563EB", "#0EA5E9"), hover_color=("#1D4ED8", "#0284C7"),
                      command=self._save).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(btns, text="Cancel", height=36,
                      fg_color=("#94A3B8", "#64748B"), hover_color=("#64748B", "#475569"),
                      command=self.destroy).pack(side="left", expand=True, fill="x")

    def _add_row_widget(self, entry):
        var = ctk.BooleanVar(value=entry.get("enabled", True))
        self._entry_rows.append([entry, var])
        row = ctk.CTkFrame(self._list_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkCheckBox(row, text=entry["label"], variable=var,
                        font=ctk.CTkFont(size=12)).pack(side="left", padx=5)

    def _auto_fy(self):
        import re
        year = self._year_entry.get().strip()
        m = re.match(r"(\d{4})-(\d{2}|\d{4})$", year)
        if not m:
            return
        y1 = int(m.group(1))
        suffix = m.group(2)
        y2 = int(str(y1)[:2] + suffix) if len(suffix) == 2 else int(suffix)
        if self._type_var.get() == "TY":
            fy = f"{y1}-{str(y2)[-2:]}"
        else:
            fy = f"{y1 - 1}-{str(y2 - 1)[-2:]}"
        self._fy_entry.delete(0, "end")
        self._fy_entry.insert(0, fy)

    def _add_entry(self):
        year_type = self._type_var.get()
        year = self._year_entry.get().strip()
        fy = self._fy_entry.get().strip()
        if not year or not fy:
            messagebox.showwarning("Missing Fields", "Please fill in Year and FY.", parent=self)
            return
        label = f"{year_type} {year} (FY {fy})"
        if any(r[0]["label"] == label for r in self._entry_rows):
            messagebox.showwarning("Duplicate", f'"{label}" already exists.', parent=self)
            return
        year_obj = {"TY": year, "FY": fy} if year_type == "TY" else {"AY": year, "FY": fy}
        new_entry = {"label": label, "enabled": True, "year": year_obj}
        self._add_row_widget(new_entry)
        self._year_entry.delete(0, "end")
        self._fy_entry.delete(0, "end")

    def _save(self):
        final = []
        for entry, var in self._entry_rows:
            entry["enabled"] = var.get()
            final.append(entry)
        try:
            with open(self._json_path, "w", encoding="utf-8") as f:
                json.dump(final, f, indent=2, ensure_ascii=False)
            self._on_save()
            self.destroy()
        except Exception as ex:
            messagebox.showerror("Save Error", str(ex), parent=self)


class AayDocCapioApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("AayDocCapio — Standalone Secure Utility")
        self.geometry("1200x780")
        self.minsize(1100, 720)

        # Write session start boundary (appended)
        try:
            with open("app.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== AayDocCapio Session Started {get_timestamp()} ===\n")
        except Exception:
            pass

        # Initialize Encryption Vault Manager
        self.vault = VaultManager()

        # State Variables
        self.selected_assessee_ids = set()
        self.editing_id = None
        self.is_running = False
        self.automation_thread = None

        # Build UI Elements
        self._build_ui()
        
        # Load and Refresh Assessee Grid
        self.refresh_grid()

    def _build_ui(self):
        # ── 1. Header Frame ──────────────────────────────────────────────────
        # Styled with Navy Blue in light mode and Dark Slate in dark mode
        self.header = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color=("#1E3A8A", "#1E293B"))
        self.header.pack(side="top", fill="x")
        self.header.pack_propagate(False)

        title_lbl = ctk.CTkLabel(
            self.header, 
            text="🏢 TAX DOWNLOADER", 
            font=ctk.CTkFont(family="Helvetica", size=18, weight="bold"), 
            text_color="#F8FAFC"
        )
        title_lbl.pack(side="left", padx=20, pady=15)

        subtitle_lbl = ctk.CTkLabel(
            self.header, 
            text="•  ITD Bulk Document Downloader (Form 26AS, AIS, TIS)", 
            font=ctk.CTkFont(family="Helvetica", size=13), 
            text_color="#CBD5E1"
        )
        subtitle_lbl.pack(side="left", pady=18)

        # Theme Switcher in the Header
        self.theme_switch = ctk.CTkSwitch(
            self.header, 
            text="Light Mode", 
            command=self.toggle_theme,
            onvalue="Dark",
            offvalue="Light",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.theme_switch.pack(side="right", padx=20, pady=15)
        
        # Match switch state with current mode
        if ctk.get_appearance_mode() == "Dark":
            self.theme_switch.select()
            self.theme_switch.configure(text="Dark Mode")
        else:
            self.theme_switch.deselect()
            self.theme_switch.configure(text="Light Mode")

    # ── 2. Footer Console Logging Frame ──────────────────────────────────
        self.footer = ctk.CTkFrame(self, height=180, corner_radius=0, fg_color=("#F8FAFC", "#0F172A"), border_width=1, border_color=("#E2E8F0", "#334155"))
        self.footer.pack(side="bottom", fill="x")
        self.footer.pack_propagate(False)

        log_header = ctk.CTkFrame(self.footer, height=30, fg_color=("#E2E8F0", "#1E293B"), corner_radius=0)
        log_header.pack(fill="x")
        log_lbl = ctk.CTkLabel(log_header, text="📟 LIVE ENGINE LOGS", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#1E3A8A", "#38BDF8"))
        log_lbl.pack(side="left", padx=15, pady=5)

        # Copy logs button
        copy_btn = ctk.CTkButton(
            log_header,
            text="📋 Copy Logs",
            width=85,
            height=22,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.copy_logs_to_clipboard,
            fg_color="transparent",
            hover_color=("#CBD5E1", "#334155"),
            text_color=("#1E3A8A", "#38BDF8")
        )
        copy_btn.pack(side="right", padx=15, pady=4)

        self.log_box = ctk.CTkTextbox(
            self.footer, 
            font=("Consolas", 11), 
            fg_color=("#FFFFFF", "#1E293B"), 
            text_color=("#0F172A", "#E2E8F0"),
            border_width=1,
            border_color=("#CBD5E1", "#334155")
        )
        self.log_box.pack(fill="both", expand=True, padx=15, pady=5)

        # ── 3. Main Split Area ───────────────────────────────────────────────
        self.split_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.split_frame.pack(fill="both", expand=True)

        # Left Column: Assessee Management Form Container
        self.left_col = ctk.CTkFrame(self.split_frame, width=335, corner_radius=0, fg_color=("#F8FAFC", "#111827"))
        self.left_col.pack(side="left", fill="y")
        self.left_col.pack_propagate(False)

        self._build_management_form()

        # Right Column: Main Working Dashboard & List
        self.right_col = ctk.CTkFrame(self.split_frame, fg_color=("#F1F5F9", "#0F172A"), corner_radius=0)
        self.right_col.pack(side="right", fill="both", expand=True)

        self._build_dashboard()

    def toggle_theme(self):
        mode = self.theme_switch.get()
        ctk.set_appearance_mode(mode)
        self.theme_switch.configure(text="Dark Mode" if mode == "Dark" else "Light Mode")

    def _build_management_form(self):
        # We put a Tabview to keep Single Add Form and Bulk Upload separated
        # This completely resolves vertical cutoffs on standard resolutions
        self.tabview = ctk.CTkTabview(
            self.left_col,
            segmented_button_selected_color=("#1E3A8A", "#0EA5E9"),
            segmented_button_selected_hover_color=("#1D4ED8", "#0284C7"),
            segmented_button_unselected_color=("#E2E8F0", "#1F2937"),
            text_color=("#0F172A", "#FFFFFF")
        )
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_single = self.tabview.add("👤 Single Profile")
        self.tab_bulk = self.tabview.add("📂 Bulk Operations")

        # ─── TAB 1: Single Profile Form ──────────────────
        tab_s = self.tab_single

        # Form Header
        form_title = ctk.CTkLabel(
            tab_s,
            text="ADD / EDIT CLIENT",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#1E3A8A", "#38BDF8")
        )
        form_title.pack(anchor="w", padx=10, pady=(6, 4))

        # Input fields
        ctk.CTkLabel(tab_s, text="Assessee Full Name:", text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=10, pady=(4, 1))
        self.entry_name = ctk.CTkEntry(tab_s, height=32, placeholder_text="e.g. John Doe", fg_color=("#FFFFFF", "#1F2937"), border_color=("#CBD5E1", "#374151"), text_color=("#0F172A", "#F8FAFC"))
        self.entry_name.pack(fill="x", padx=10, pady=(0, 2))

        ctk.CTkLabel(tab_s, text="PAN Number (10 characters):", text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=10, pady=(4, 1))
        self.entry_pan = ctk.CTkEntry(tab_s, height=32, placeholder_text="e.g. AAAPT0001A", fg_color=("#FFFFFF", "#1F2937"), border_color=("#CBD5E1", "#374151"), text_color=("#0F172A", "#F8FAFC"))
        self.entry_pan.pack(fill="x", padx=10, pady=(0, 2))

        ctk.CTkLabel(tab_s, text="Date of Birth (DD-MM-YYYY):", text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=10, pady=(4, 1))
        self.entry_dob = ctk.CTkEntry(tab_s, height=32, placeholder_text="e.g. 01-01-1980", fg_color=("#FFFFFF", "#1F2937"), border_color=("#CBD5E1", "#374151"), text_color=("#0F172A", "#F8FAFC"))
        self.entry_dob.pack(fill="x", padx=10, pady=(0, 2))

        ctk.CTkLabel(tab_s, text="ITD Portal Password:", text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=10, pady=(4, 1))
        self.entry_pwd = ctk.CTkEntry(tab_s, height=32, placeholder_text="Enter Password", show="*", fg_color=("#FFFFFF", "#1F2937"), border_color=("#CBD5E1", "#374151"), text_color=("#0F172A", "#F8FAFC"))
        self.entry_pwd.pack(fill="x", padx=10, pady=(0, 1))
        self._show_pwd_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(tab_s, text="Show password", variable=self._show_pwd_var,
                        text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=11),
                        command=lambda: self.entry_pwd.configure(show="" if self._show_pwd_var.get() else "*")
                        ).pack(anchor="w", padx=12, pady=(0, 2))

        # Form Button Tray
        self.btn_save = ctk.CTkButton(
            tab_s,
            text="💾 Save Profile",
            fg_color=("#2563EB", "#0EA5E9"),
            hover_color=("#1D4ED8", "#0284C7"),
            height=36,
            font=ctk.CTkFont(weight="bold"),
            command=self.save_assessee
        )
        self.btn_save.pack(fill="x", padx=10, pady=(10, 4))

        self.btn_clear = ctk.CTkButton(
            tab_s,
            text="🧹 Clear Fields",
            fg_color=("#64748B", "#374151"),
            hover_color=("#475569", "#4B5563"),
            height=28,
            text_color="#FFFFFF",
            command=self.clear_form
        )
        self.btn_clear.pack(fill="x", padx=10, pady=(0, 6))

        # ─── TAB 2: Bulk Operations ──────────────────
        tab_b = self.tab_bulk

        bulk_title = ctk.CTkLabel(
            tab_b, 
            text="BULK DATA OPERATIONS", 
            font=ctk.CTkFont(size=12, weight="bold"), 
            text_color=("#16A34A", "#10B981")
        )
        bulk_title.pack(anchor="w", padx=10, pady=(10, 15))

        # Helpful hints box
        help_frame = ctk.CTkFrame(tab_b, fg_color=("#F1F5F9", "#1F2937"), border_width=1, border_color=("#E2E8F0", "#374151"))
        help_frame.pack(fill="x", padx=10, pady=(0, 20))
        
        help_text = (
            "💡 Quick Instructions:\n\n"
            "1. Generate an Excel template first.\n"
            "2. Fill Name, PAN, DOB, Password.\n"
            "3. Click Import CSV / Excel below to\n"
            "   automatically batch-load all records."
        )
        help_lbl = ctk.CTkLabel(
            help_frame, 
            text=help_text, 
            font=ctk.CTkFont(size=11), 
            text_color=("#475569", "#94A3B8"),
            justify="left",
            padx=12,
            pady=12
        )
        help_lbl.pack(anchor="w")

        self.btn_bulk_import = ctk.CTkButton(
            tab_b, 
            text="📥 Import CSV / Excel", 
            fg_color=("#16A34A", "#10B981"), 
            hover_color=("#15803D", "#059669"), 
            height=38,
            font=ctk.CTkFont(weight="bold"), 
            command=self.bulk_import
        )
        self.btn_bulk_import.pack(fill="x", padx=10, pady=5)

        self.btn_template = ctk.CTkButton(
            tab_b, 
            text="📄 Generate Upload Template", 
            fg_color="transparent", 
            text_color=("#16A34A", "#10B981"),
            border_width=1,
            border_color=("#16A34A", "#10B981"),
            hover_color=("#DCFCE7", "#064E3B"), 
            height=35,
            font=ctk.CTkFont(weight="bold"), 
            command=self.generate_template
        )
        self.btn_template.pack(fill="x", padx=10, pady=5)

    def _build_dashboard(self):
        # Settings Bar (Upper Row)
        settings_frame = ctk.CTkFrame(self.right_col, fg_color=("#FFFFFF", "#1E293B"), corner_radius=8, border_width=1, border_color=("#E2E8F0", "#334155"))
        settings_frame.pack(fill="x", padx=20, pady=(15, 10))

        # 1. Assessment Year Selector — loaded from assessment_years.json
        self._ay_entries = self._load_ay_list()
        ay_labels = [e["label"] for e in self._ay_entries if e.get("enabled", True)]

        ay_lbl = ctk.CTkLabel(settings_frame, text="📅 Assessment Year:", text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=11, weight="bold"))
        ay_lbl.grid(row=0, column=0, sticky="w", padx=(15, 10), pady=(12, 2))

        saved_ay = self.vault.get_setting("assessment_year", "Select AY/TY")
        self.ay_combo = ctk.CTkComboBox(
            settings_frame,
            values=ay_labels,
            width=220,
            fg_color=("#FFFFFF", "#1F2937"),
            border_color=("#CBD5E1", "#374151"),
            button_color=("#CBD5E1", "#374151"),
            text_color=("#0F172A", "#F8FAFC"),
            command=self.save_ay_setting
        )
        self.ay_combo.set(saved_ay if saved_ay in ay_labels else "Select AY/TY")
        self.ay_combo.grid(row=1, column=0, padx=(15, 10), pady=(2, 4), sticky="w")

        ctk.CTkButton(
            settings_frame, text="⚙ Manage Years", height=24, width=220,
            fg_color="transparent", border_width=1,
            border_color=("#CBD5E1", "#374151"), text_color=("#475569", "#94A3B8"),
            font=ctk.CTkFont(size=11), hover_color=("#F1F5F9", "#1E293B"),
            command=self.open_manage_years
        ).grid(row=2, column=0, padx=(15, 10), pady=(0, 12), sticky="w")

        # 2. Documents To Download
        doc_lbl = ctk.CTkLabel(settings_frame, text="📋 Documents to Download:", text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=11, weight="bold"))
        doc_lbl.grid(row=0, column=1, sticky="w", padx=(10, 10), pady=(12, 2))
        
        doc_checkbox_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        doc_checkbox_frame.grid(row=1, column=1, padx=(10, 10), pady=(2, 12), sticky="w")
        
        self.dl_26as_var = ctk.BooleanVar(value=True)
        self.chk_26as = ctk.CTkCheckBox(doc_checkbox_frame, text="26AS", variable=self.dl_26as_var, width=70, text_color=("#0F172A", "#F8FAFC"))
        self.chk_26as.pack(side="left")
        
        self.dl_ais_var = ctk.BooleanVar(value=True)
        self.chk_ais = ctk.CTkCheckBox(doc_checkbox_frame, text="AIS", variable=self.dl_ais_var, width=70, text_color=("#0F172A", "#F8FAFC"))
        self.chk_ais.pack(side="left")

        self.dl_tis_var = ctk.BooleanVar(value=True)
        self.chk_tis = ctk.CTkCheckBox(doc_checkbox_frame, text="TIS", variable=self.dl_tis_var, width=70, text_color=("#0F172A", "#F8FAFC"))
        self.chk_tis.pack(side="left")

        # 3. Target Directory Selector
        dir_lbl = ctk.CTkLabel(settings_frame, text="📂 Output Directory Path:", text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=11, weight="bold"))
        dir_lbl.grid(row=0, column=2, sticky="w", padx=(20, 10), pady=(12, 2))

        dir_selector_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        dir_selector_frame.grid(row=1, column=2, padx=(20, 10), pady=(2, 12), sticky="ew")

        # Default path setup
        default_dir = self.vault.get_setting("download_root_dir", os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs"))
        self.output_dir_lbl = ctk.CTkLabel(dir_selector_frame, text=default_dir, font=ctk.CTkFont(size=12), text_color=("#0F172A", "#E2E8F0"), width=250, anchor="w")
        self.output_dir_lbl.pack(side="left", padx=5)

        self.btn_select_dir = ctk.CTkButton(
            dir_selector_frame, 
            text="📂 Browse...", 
            width=85, 
            height=28,
            fg_color=("#E2E8F0", "#374151"), 
            hover_color=("#CBD5E1", "#4B5563"),
            text_color=("#0F172A", "#FFFFFF"),
            command=self.browse_output_dir
        )
        self.btn_select_dir.pack(side="right", padx=(10, 5))

        # Configure grid expansion
        settings_frame.grid_columnconfigure(2, weight=1)

        # ── Middle Area: Scrollable Client Grid ──
        grid_lbl_frame = ctk.CTkFrame(self.right_col, fg_color="transparent")
        grid_lbl_frame.pack(fill="x", padx=25, pady=(10, 0))
        
        ctk.CTkLabel(grid_lbl_frame, text="👥 CLIENT/ASSESSEE VAULT LISTING", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#475569", "#94A3B8")).pack(side="left")
        self.lbl_selected_count = ctk.CTkLabel(grid_lbl_frame, text="0 Selected", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#2563EB", "#38BDF8"))
        self.lbl_selected_count.pack(side="right")

        # Header Columns Row
        headers_frame = ctk.CTkFrame(self.right_col, fg_color=("#E2E8F0", "#0F172A"), height=35, corner_radius=8)
        headers_frame.pack(fill="x", padx=20, pady=5)
        headers_frame.pack_propagate(False)

        ctk.CTkLabel(headers_frame, text="✅ Select", width=60, font=ctk.CTkFont(size=11, weight="bold"), text_color=("#475569", "#CBD5E1")).pack(side="left", padx=5)
        ctk.CTkLabel(headers_frame, text="👤 Assessee Name", anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#475569", "#CBD5E1")).pack(side="left", fill="x", expand=True, padx=10)
        ctk.CTkLabel(headers_frame, text="💳 PAN Number", width=120, anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#475569", "#CBD5E1")).pack(side="left", padx=10)
        ctk.CTkLabel(headers_frame, text="📅 Date of Birth", width=100, anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#475569", "#CBD5E1")).pack(side="left", padx=10)
        ctk.CTkLabel(headers_frame, text="⚙️ Actions", width=150, font=ctk.CTkFont(size=11, weight="bold"), text_color=("#475569", "#CBD5E1")).pack(side="right", padx=15)

        # Scrollable panel
        self.list_frame = ctk.CTkScrollableFrame(self.right_col, fg_color="transparent", scrollbar_button_color=("#CBD5E1", "#374151"))
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # ── Lower Area: Execution Control Panel ──
        self.control_bar = ctk.CTkFrame(self.right_col, fg_color=("#FFFFFF", "#0F172A"), height=70, corner_radius=12, border_width=1, border_color=("#E2E8F0", "#334155"))
        self.control_bar.pack(fill="x", padx=20, pady=(5, 15))
        self.control_bar.pack_propagate(False)

        # Select All Checkbox
        self.select_all_var = ctk.BooleanVar(value=False)
        self.chk_select_all = ctk.CTkCheckBox(
            self.control_bar, 
            text="Select All Clients", 
            variable=self.select_all_var, 
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0F172A", "#FFFFFF"),
            command=self.toggle_select_all
        )
        self.chk_select_all.pack(side="left", padx=25, pady=20)

        # Execution Buttons
        self.btn_run = ctk.CTkButton(
            self.control_bar, 
            text="▶  START AUTO DOWNLOAD", 
            fg_color=("#16A34A", "#10B981"), 
            hover_color=("#15803D", "#059669"), 
            width=220, 
            height=40,
            font=ctk.CTkFont(size=13, weight="bold"), 
            command=self.start_automation
        )
        self.btn_run.pack(side="right", padx=15, pady=15)

        self.btn_stop = ctk.CTkButton(
            self.control_bar, 
            text="⏹  STOP RUN", 
            fg_color=("#EF4444", "#EF4444"), 
            hover_color=("#DC2626", "#DC2626"), 
            width=120, 
            height=40,
            font=ctk.CTkFont(size=13, weight="bold"), 
            state="disabled",
            command=self.stop_automation
        )
        self.btn_stop.pack(side="right", padx=5, pady=15)

    # ── Grid Rendering and Data Handoff ──────────────────────────────────────
    
    def refresh_grid(self):
        # Clear existing rows
        for widget in self.list_frame.winfo_children():
            widget.destroy()

        self.assessee_list = self.vault.get_all_assessees()
        self.checkbox_vars = {}

        if not self.assessee_list:
            no_lbl = ctk.CTkLabel(self.list_frame, text="No clients registered. Use the profile form or bulk upload template to add assessees.", text_color=("#475569", "#94A3B8"), pady=40)
            no_lbl.pack(fill="x")
            self.chk_select_all.configure(state="disabled")
            self.lbl_selected_count.configure(text="0 Selected")
            return

        self.chk_select_all.configure(state="normal")
        
        for index, a in enumerate(self.assessee_list):
            a_id = a.get("id")
            
            # Row container (Alternating colors)
            row_bg = ("#E2E8F0", "#1F2937") if index % 2 == 0 else ("#F8FAFC", "#0F172A")
            row_frame = ctk.CTkFrame(self.list_frame, fg_color=row_bg, height=45, corner_radius=6)
            row_frame.pack(fill="x", pady=2, ipady=4)
            
            # Checkbox
            is_checked = a_id in self.selected_assessee_ids
            self.checkbox_vars[a_id] = ctk.BooleanVar(value=is_checked)
            cb = ctk.CTkCheckBox(
                row_frame, 
                text="", 
                variable=self.checkbox_vars[a_id], 
                width=30,
                command=lambda id_val=a_id: self.on_checkbox_click(id_val)
            )
            cb.pack(side="left", padx=(15, 5))

            # Assessee details labels
            name_lbl = ctk.CTkLabel(row_frame, text=a.get("name"), anchor="w", text_color=("#0F172A", "#F8FAFC"), font=ctk.CTkFont(size=13))
            name_lbl.pack(side="left", fill="x", expand=True, padx=10)

            pan_lbl = ctk.CTkLabel(row_frame, text=a.get("pan"), width=120, anchor="w", text_color=("#2563EB", "#38BDF8"), font=ctk.CTkFont(size=13, weight="bold"))
            pan_lbl.pack(side="left", padx=10)

            dob_lbl = ctk.CTkLabel(row_frame, text=a.get("dob"), width=100, anchor="w", text_color=("#475569", "#94A3B8"), font=ctk.CTkFont(size=13))
            dob_lbl.pack(side="left", padx=10)

            # Action Buttons Frame
            action_tray = ctk.CTkFrame(row_frame, fg_color="transparent")
            action_tray.pack(side="right", padx=15)

            # Edit Button
            edit_btn = ctk.CTkButton(
                action_tray, 
                text="✏️ Edit", 
                width=65, 
                height=25, 
                fg_color=("#0284C7", "#0284C7"), 
                hover_color=("#0369A1", "#0369A1"),
                font=ctk.CTkFont(size=11), 
                command=lambda a_val=a: self.load_for_editing(a_val)
            )
            edit_btn.pack(side="left", padx=2)

            # Delete Button
            del_btn = ctk.CTkButton(
                action_tray, 
                text="🗑️ Delete", 
                width=65, 
                height=25, 
                fg_color=("#DC2626", "#DC2626"), 
                hover_color=("#991B1B", "#991B1B"),
                font=ctk.CTkFont(size=11), 
                command=lambda id_val=a_id: self.delete_assessee(id_val)
            )
            del_btn.pack(side="left", padx=2)

        self._update_selected_count_ui()

    def on_checkbox_click(self, id_val):
        if self.checkbox_vars[id_val].get():
            self.selected_assessee_ids.add(id_val)
        else:
            self.selected_assessee_ids.discard(id_val)
        self._update_selected_count_ui()

    def toggle_select_all(self):
        select_all = self.select_all_var.get()
        for a_id, var in self.checkbox_vars.items():
            var.set(select_all)
            if select_all:
                self.selected_assessee_ids.add(a_id)
            else:
                self.selected_assessee_ids.discard(a_id)
        self._update_selected_count_ui()

    def _update_selected_count_ui(self):
        count = len(self.selected_assessee_ids)
        self.lbl_selected_count.configure(text=f"{count} Selected")
        
        # Keep "Select All" status synced
        if len(self.checkbox_vars) > 0 and count == len(self.checkbox_vars):
            self.select_all_var.set(True)
        else:
            self.select_all_var.set(False)

    # ── Form Operations ──────────────────────────────────────────────────────

    def load_for_editing(self, a):
        self.editing_id = a.get("id")
        self.entry_name.delete(0, "end")
        self.entry_name.insert(0, a.get("name", ""))
        self.entry_pan.delete(0, "end")
        self.entry_pan.insert(0, a.get("pan", ""))
        self.entry_dob.delete(0, "end")
        self.entry_dob.insert(0, a.get("dob", ""))
        self.entry_pwd.delete(0, "end")
        self.entry_pwd.insert(0, a.get("password", ""))
        self.btn_save.configure(text="💾 Update Profile", fg_color=("#EAB308", "#EAB308"), hover_color=("#CA8A04", "#CA8A04"))
        
        # Switch tab automatically to edit form
        self.tabview.set("👤 Single Profile")

    def clear_form(self):
        self.editing_id = None
        self.entry_name.delete(0, "end")
        self.entry_pan.delete(0, "end")
        self.entry_dob.delete(0, "end")
        self.entry_pwd.delete(0, "end")
        self.btn_save.configure(text="💾 Save Profile", fg_color=("#2563EB", "#0EA5E9"), hover_color=("#1D4ED8", "#0284C7"))

    def save_assessee(self):
        name = self.entry_name.get()
        pan = self.entry_pan.get()
        dob = self.entry_dob.get()
        pwd = self.entry_pwd.get()

        try:
            self.vault.add_update_assessee(name, pan, dob, pwd, self.editing_id)
            action = "updated" if self.editing_id else "added"
            self.log(f"[Vault] Profile {pan} successfully {action}.")
            self.clear_form()
            self.refresh_grid()
        except ValueError as ve:
            messagebox.showerror("Validation Error", str(ve))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save profile: {e}")

    def delete_assessee(self, assessee_id):
        confirm = messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this assessee from the vault?")
        if confirm:
            try:
                self.vault.delete_assessee(assessee_id)
                self.selected_assessee_ids.discard(assessee_id)
                self.log("[Vault] Assessee deleted from vault.")
                self.refresh_grid()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete: {e}")

    # ── Settings Operations ──────────────────────────────────────────────────

    def browse_output_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir_lbl.cget("text"))
        if chosen:
            self.output_dir_lbl.configure(text=chosen)
            self.vault.update_setting("download_root_dir", chosen)
            self.log(f"[Settings] Output folder updated to: {chosen}")

    def _load_ay_list(self):
        """Load assessment year entries from assessment_years.json next to app.py."""
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assessment_years.json")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return [
                {"label": "AY 2025-26 (FY 2024-25)", "year": {"AY": "2025-26", "FY": "2024-25"}},
                {"label": "AY 2024-25 (FY 2023-24)", "year": {"AY": "2024-25", "FY": "2023-24"}},
            ]

    def _resolve_ay_fy(self, label: str):
        """Return (traces_year, ais_year) for the selected dropdown label.
        TRACES uses AY when available, otherwise TY.  AIS portal always uses FY."""
        for e in self._ay_entries:
            if e["label"] == label:
                y = e["year"]
                traces_year = y.get("AY") or y.get("TY")
                ais_year = y.get("FY")
                return traces_year, ais_year
        return None, None

    def open_manage_years(self):
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assessment_years.json")
        ManageYearsDialog(self, json_path, on_save=self.refresh_ay_combo)

    def refresh_ay_combo(self):
        self._ay_entries = self._load_ay_list()
        ay_labels = [e["label"] for e in self._ay_entries if e.get("enabled", True)]
        current = self.ay_combo.get()
        self.ay_combo.configure(values=ay_labels)
        self.ay_combo.set(current if current in ay_labels else "Select AY/TY")
        self.log("[Settings] Assessment Year list refreshed.")

    def save_ay_setting(self, val):
        self.vault.update_setting("assessment_year", val)
        self.log(f"[Settings] Target Assessment Year updated to: {val}")

    # ── Live Logging Console ─────────────────────────────────────────────────

    def log(self, message):
        ts = get_timestamp()
        text_entry = f"[{ts}] {message}\n"
        
        # Thread-safe insert
        self.after(0, lambda: self._insert_log(text_entry))

        # Write to log file
        try:
            with open("app.log", "a", encoding="utf-8") as f:
                f.write(text_entry)
        except Exception:
            pass

    def _insert_log(self, text_entry):
        self.log_box.insert("end", text_entry)
        self.log_box.see("end")

    def copy_logs_to_clipboard(self):
        try:
            content = self.log_box.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(content)
            self.log("[System] Logs successfully copied to clipboard.")
        except Exception as e:
            self.log(f"[System Error] Failed to copy logs: {e}")

    # ── Bulk Imports & Templates ─────────────────────────────────────────────

    def bulk_import(self):
        file_path = filedialog.askopenfilename(filetypes=[("Excel / CSV files", "*.xlsx;*.csv")])
        if not file_path:
            return

        self.log(f"[Vault] Loading bulk import from {os.path.basename(file_path)}...")
        count, errors = self.vault.import_bulk(file_path)
        
        self.log(f"[Vault] Successfully imported/updated {count} profiles.")
        if errors:
            self.log("[Warning] Bulk Import anomalies detected:")
            for err in errors:
                self.log(f"  - {err}")
            messagebox.showwarning("Bulk Import Complete", f"Imported {count} profiles with {len(errors)} warnings. Check logs for details.")
        else:
            messagebox.showinfo("Success", f"Bulk import complete! {count} profiles loaded.")
            
        self.refresh_grid()

    def generate_template(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", 
            filetypes=[("Excel Workbook", "*.xlsx"), ("CSV UTF-8", "*.csv")],
            initialfile="Assessee_Import_Template"
        )
        if not file_path:
            return
            
        try:
            self.vault.generate_template(file_path)
            self.log(f"[Vault] Bulk upload template generated at: {file_path}")
            messagebox.showinfo("Success", f"Template successfully generated at:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate template: {e}")

    # ── Playwright Automation Execution Thread ────────────────────────────────

    def start_automation(self):
        if self.is_running:
            return

        if not self.selected_assessee_ids:
            messagebox.showwarning("Selection Required", "Please select at least one client/assessee for download.")
            return

        # Fetch settings
        ay_label = self.ay_combo.get()
        if ay_label == "Select AY/TY" or not ay_label:
            messagebox.showwarning("Selection Required", "Please select an Assessment / Tax Year before running.")
            return
        ay, fy = self._resolve_ay_fy(ay_label)
        if not ay:
            messagebox.showwarning("Invalid Selection", f"Could not resolve year for: {ay_label}")
            return

        root_dir = self.output_dir_lbl.cget("text")

        dl_26as = self.dl_26as_var.get()
        dl_ais = self.dl_ais_var.get()
        dl_tis = self.dl_tis_var.get()

        if not (dl_26as or dl_ais or dl_tis):
            messagebox.showwarning("Selection Required", "Please select at least one document type (26AS, AIS, or TIS) to download.")
            return

        self.is_running = True
        self.btn_run.configure(state="disabled", text="⏳ RUNNING...")
        self.btn_stop.configure(state="normal")
        self._lock_ui(True)

        # Clear logs screen
        self.log_box.delete("1.0", "end")
        self.log("[System] Launching Background Automation Session...")

        # Setup selected targets list
        targets = [a for a in self.assessee_list if a.get("id") in self.selected_assessee_ids]

        # Dispatch async automation worker thread
        self.automation_thread = threading.Thread(
            target=self._run_automation_wrapper,
            args=(targets, ay, root_dir, dl_26as, dl_ais, dl_tis)
        )
        self.automation_thread.daemon = True
        self.automation_thread.start()

    def stop_automation(self):
        if not self.is_running:
            return
        
        confirm = messagebox.askyesno("Stop Protocol", "Forcefully abort the active automation batch?")
        if confirm:
            self.log("[System] Force abort request received. Closing Chromium engines...")
            self.is_running = False

    def _lock_ui(self, lock: bool):
        state = "disabled" if lock else "normal"
        self.entry_name.configure(state=state)
        self.entry_pan.configure(state=state)
        self.entry_dob.configure(state=state)
        self.entry_pwd.configure(state=state)
        self.btn_save.configure(state=state)
        self.btn_clear.configure(state=state)
        self.btn_bulk_import.configure(state=state)
        self.btn_template.configure(state=state)
        self.ay_combo.configure(state=state)
        self.chk_26as.configure(state=state)
        self.chk_ais.configure(state=state)
        self.chk_tis.configure(state=state)
        self.btn_select_dir.configure(state=state)
        self.chk_select_all.configure(state=state)

    def _run_automation_wrapper(self, targets, ay, root_dir, dl_26as, dl_ais, dl_tis):
        # Create event loop inside this thread for asyncio Playwright commands
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(
                self._execute_batch(targets, ay, root_dir, dl_26as, dl_ais, dl_tis)
            )
        except Exception as e:
            self.log(f"[System Error] Batch thread crashed: {e}")
        finally:
            loop.close()
            # Restore UI controls
            self.is_running = False
            self.after(0, lambda: self.btn_run.configure(state="normal", text="▶  START AUTO DOWNLOAD"))
            self.after(0, lambda: self.btn_stop.configure(state="disabled"))
            self.after(0, lambda: self._lock_ui(False))
            self.log("[System] Handoff Complete. Engine Idle.")

    async def _execute_batch(self, targets, ay, root_dir, dl_26as, dl_ais, dl_tis):
        self.log(f"[System] Initiating batch run for {len(targets)} assessees. AY: {ay}")
        
        # Initialize Playwright Browser Manager
        try:
            # We run interactive=True (headful) so browser is visible for monitoring / captcha check
            context = await browser_manager.get_context(log_callback=self.log, interactive=True)
        except Exception as e:
            self.log(f"[System Error] Failed to initialize Playwright context: {e}")
            return

        for index, target in enumerate(targets):
            if not self.is_running:
                self.log("[System] Execution aborted by user.")
                break

            name = target.get("name")
            pan = target.get("pan")
            dob = target.get("dob")
            pwd = target.get("password")

            self.log(f"──────────────────────────────────────────────────")
            self.log(f"[{index+1}/{len(targets)}] Starting Assessee: {name} ({pan})")
            
            # Setup dedicated folder: root_dir/PAN-Name/AY_YYYY_YY/
            name_sanitized = "".join([c if c.isalnum() or c in " _-" else "" for c in name])
            client_folder = f"{pan}-{name_sanitized}"
            ay_folder = f"AY_{ay.replace('-', '_')}"
            output_path = os.path.join(root_dir, client_folder, ay_folder)
            
            page = None
            try:
                # 1. Login
                page = await login_itd(pan, pwd, self.log, context)
                
                # 2. Download Form 26AS
                success_26as = True
                if dl_26as and self.is_running:
                    success_26as = await download_26as(page, ay, output_path, self.log, pan=pan)  # ay = Assessment Year for TRACES

                # 3. Download AIS / TIS
                success_ais_tis = True
                if (dl_ais or dl_tis) and self.is_running:
                    # Bring page to front and go to dashboard to be safe
                    try:
                        await page.bring_to_front()
                        if "dashboard" not in page.url.lower():
                            await page.goto("https://eportal.incometax.gov.in/iec/fo/dashboard", wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(2)
                    except Exception:
                        pass
                    success_ais_tis = await download_ais_tis(page, fy, output_path, self.log, pan=pan)  # fy = Financial Year for AIS portal

                # 4. Logout
                if self.is_running:
                    await logout_itd(page, self.log)
                    page = None

                all_ok = (not dl_26as or success_26as) and (not (dl_ais or dl_tis) or success_ais_tis)
                if all_ok:
                    self.log(f"[Victory] Assessee {pan} — all selected documents downloaded successfully.")
                else:
                    self.log(f"[Warning] Assessee {pan} — completed with errors. Check logs above for details.")

            except Exception as e:
                self.log(f"[Error] Failed to process assessee {pan}: {e}")
                # Try to logout to clean state for next assessee
                if page:
                    try:
                        await logout_itd(page, self.log)
                    except Exception:
                        pass
            # Brief pause between accounts
            await asyncio.sleep(3)

        # Cleanup browser resources
        await browser_manager.close()
        self.log(f"──────────────────────────────────────────────────")
        self.log("[System] Batch download run finished.")

if __name__ == "__main__":
    app = AayDocCapioApp()
    app.mainloop()
