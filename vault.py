import os
import re
import json
import uuid
import datetime
import pandas as pd
from base64 import urlsafe_b64encode
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_PAN_RE = re.compile(r'^[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]$')
_DOB_RE = re.compile(r'^(\d{2})-(\d{2})-(\d{4})$')

# Accepted import formats → normalised DD-MM-YYYY
_DOB_FORMATS = [
    '%d-%m-%Y',   # 06-07-1974  (already correct)
    '%d/%m/%Y',   # 06/07/1974
    '%d.%m.%Y',   # 06.07.1974
    '%Y-%m-%d',   # 1974-07-06  (ISO)
    '%Y/%m/%d',   # 1974/07/06
    '%d-%m-%y',   # 06-07-74
    '%d/%m/%y',   # 06/07/74
    '%d.%m.%y',   # 06.07.74
    '%d %m %Y',   # 06 07 1974
    '%d %B %Y',   # 06 July 1974
    '%d-%B-%Y',   # 06-July-1974
]

def _normalise_dob(raw: str) -> str:
    """Convert any recognised date string to DD-MM-YYYY; return raw if unrecognised."""
    # Strip time component if present (e.g. "06/07/1974 00:00:00")
    s = raw.strip().split(' ')[0].split('T')[0]
    for fmt in _DOB_FORMATS:
        try:
            return datetime.datetime.strptime(s, fmt).strftime('%d-%m-%Y')
        except ValueError:
            continue
    # Last resort: try pandas parser
    try:
        return pd.to_datetime(s, dayfirst=True).strftime('%d-%m-%Y')
    except Exception:
        pass
    return raw.strip()  # let _validate_fields report the error with the original value

def _validate_fields(name: str, pan: str, dob: str, password: str):
    name = name.strip()
    pan  = pan.strip().upper()
    dob  = dob.strip()

    if not name:
        raise ValueError("Full Name is required.")
    if len(name) < 2:
        raise ValueError("Full Name must be at least 2 characters.")

    if not pan:
        raise ValueError("PAN Number is required.")
    if not _PAN_RE.match(pan):
        raise ValueError(
            "Invalid PAN format.\n\n"
            "Format: AAA · T · N · 0001 · Z\n"
            "  · Characters 1–3 : any letters\n"
            "  · Character 4    : P/C/H/F/A/T/B/L/J/G (taxpayer type)\n"
            "  · Character 5    : first letter of name\n"
            "  · Characters 6–9 : 4 digits\n"
            "  · Character 10   : any letter\n\n"
            "Example: AAAPT0001A")

    if not dob:
        raise ValueError("Date of Birth is required.")
    m = _DOB_RE.match(dob)
    if not m:
        raise ValueError("Date of Birth must be in DD-MM-YYYY format.\nExample: 01-01-1980")
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        dt = datetime.date(year, month, day)
    except ValueError:
        raise ValueError(f"'{dob}' is not a valid date. Please use DD-MM-YYYY.")
    today = datetime.date.today()
    if dt >= today:
        raise ValueError("Date of Birth cannot be today or a future date.")
    if year < 1900:
        raise ValueError("Date of Birth year seems incorrect (before 1900).")

    if not password:
        raise ValueError("Portal Password is required.")
    if len(password) < 4:
        raise ValueError("Password is too short (minimum 4 characters).")

class VaultManager:
    """
    Manages secure CRUD operations for Standalone Tax Downloader.
    Stores details in an encrypted local JSON vault.
    """
    def __init__(self, vault_path=None, master_password="automated_tax_app_key"):
        if vault_path is None:
            # Place in the same directory as this file
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.vault_file = os.path.join(base_dir, "tax_vault.json")
        else:
            self.vault_file = vault_path
        
        # Derive cryptographic key
        salt = b'secure_tax_salt'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        self._key = urlsafe_b64encode(kdf.derive(master_password.encode()))
        self._cipher = Fernet(self._key)
        
        # Initialize and migrate/ensure schema
        self._ensure_vault()

    def _ensure_vault(self):
        dir_name = os.path.dirname(self.vault_file)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        if not os.path.exists(self.vault_file):
            self._save_raw({"assessees": [], "settings": {}})
        else:
            data = self._get_raw()
            updated = False
            if "assessees" not in data:
                data["assessees"] = []
                updated = True
            if "settings" not in data:
                data["settings"] = {}
                updated = True
            
            # Migrate old entries if needed (add uuid, clean up keys)
            for entry in data["assessees"]:
                if "id" not in entry:
                    entry["id"] = str(uuid.uuid4())
                    updated = True
                if "pan" in entry:
                    entry["pan"] = entry["pan"].strip().upper()
            
            if updated:
                self._save_raw(data)

    def _get_raw(self):
        try:
            with open(self.vault_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"assessees": [], "settings": {}}

    def _save_raw(self, data):
        with open(self.vault_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def encrypt_password(self, password: str) -> str:
        if not password:
            return ""
        return self._cipher.encrypt(password.encode('utf-8')).decode('utf-8')

    def decrypt_password(self, encrypted_pwd: str) -> str:
        if not encrypted_pwd:
            return ""
        try:
            return self._cipher.decrypt(encrypted_pwd.encode('utf-8')).decode('utf-8')
        except Exception:
            return ""

    # --- Assessee CRUD Operations ---

    def get_all_assessees(self):
        """Returns all assessees with decrypted passwords for utility."""
        raw_data = self._get_raw()
        assessees = []
        for a in raw_data.get("assessees", []):
            decrypted = a.copy()
            decrypted["password"] = self.decrypt_password(a.get("password_enc", ""))
            assessees.append(decrypted)
        return assessees

    def add_update_assessee(self, name: str, pan: str, dob: str, password: str, assessee_id: str = None) -> str:
        """Adds or updates a single assessee."""
        raw_data = self._get_raw()
        _validate_fields(name, pan, dob, password)
        pan = pan.strip().upper()
        
        password_enc = self.encrypt_password(password)
        
        found = False
        if assessee_id:
            # Update by ID
            for i, a in enumerate(raw_data["assessees"]):
                if a.get("id") == assessee_id:
                    raw_data["assessees"][i] = {
                        "id": assessee_id,
                        "name": name.strip(),
                        "pan": pan,
                        "dob": dob.strip(),
                        "password_enc": password_enc
                    }
                    found = True
                    break
        else:
            # Check if PAN already exists to update it, or treat as new
            for i, a in enumerate(raw_data["assessees"]):
                if a.get("pan") == pan:
                    assessee_id = a.get("id") or str(uuid.uuid4())
                    raw_data["assessees"][i] = {
                        "id": assessee_id,
                        "name": name.strip(),
                        "pan": pan,
                        "dob": dob.strip(),
                        "password_enc": password_enc
                    }
                    found = True
                    break
        
        if not found:
            new_id = str(uuid.uuid4())
            raw_data["assessees"].append({
                "id": new_id,
                "name": name.strip(),
                "pan": pan,
                "dob": dob.strip(),
                "password_enc": password_enc
            })
            assessee_id = new_id

        self._save_raw(raw_data)
        return assessee_id

    def delete_assessee(self, assessee_id: str):
        """Deletes an assessee by ID."""
        raw_data = self._get_raw()
        raw_data["assessees"] = [a for a in raw_data["assessees"] if a.get("id") != assessee_id]
        self._save_raw(raw_data)

    # --- Bulk Import / Export ---

    def import_bulk(self, file_path: str) -> tuple:
        """
        Imports assessees from an Excel (.xlsx) or CSV (.csv) file.
        Expects columns: Name, PAN, DOB, Password
        Returns: (success_count, error_messages_list)
        """
        if not os.path.exists(file_path):
            return 0, [f"File {file_path} does not exist."]
        
        try:
            if file_path.endswith('.xlsx'):
                df = pd.read_excel(file_path)
            elif file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                return 0, ["Unsupported file format. Please use Excel (.xlsx) or CSV (.csv)."]
        except Exception as e:
            return 0, [f"Failed to read file: {str(e)}"]

        # Normalize column headers
        df.columns = [str(c).strip().lower() for c in df.columns]
        required_cols = {'name', 'pan', 'dob', 'password'}
        missing = required_cols - set(df.columns)
        if missing:
            return 0, [f"Missing required columns: {', '.join(missing)}. Headers must include: Name, PAN, DOB, Password."]

        added_count = 0
        updated_count = 0
        errors = []

        existing_pans = {a.get("pan") for a in self.get_all_assessees()}

        for idx, row in df.iterrows():
            row_num = idx + 2  # Excel row is 1-indexed plus header row
            try:
                name = str(row['name']).strip() if pd.notna(row['name']) else ""
                pan = str(row['pan']).strip().upper() if pd.notna(row['pan']) else ""

                # Format DOB as string (handle datetime objects or floats from Excel)
                dob_val = row['dob']
                try:
                    is_null = pd.isna(dob_val)
                except (TypeError, ValueError):
                    is_null = False
                if is_null:
                    dob = ""
                elif isinstance(dob_val, (pd.Timestamp, datetime.datetime, datetime.date)):
                    dob = pd.Timestamp(dob_val).strftime('%d-%m-%Y')
                else:
                    dob = _normalise_dob(str(dob_val).strip())

                password = str(row['password']).strip() if pd.notna(row['password']) else ""

                if not name or not pan or not dob or not password:
                    errors.append(f"Row {row_num}: Missing values in Name, PAN, DOB, or Password.")
                    continue

                if len(pan) != 10:
                    errors.append(f"Row {row_num}: Invalid PAN length (must be 10 characters).")
                    continue

                is_existing = pan in existing_pans
                self.add_update_assessee(name, pan, dob, password)
                if is_existing:
                    updated_count += 1
                else:
                    existing_pans.add(pan)
                    added_count += 1
            except Exception as e:
                errors.append(f"Row {row_num}: Error importing entry: {str(e)}")

        return added_count, updated_count, errors

    def generate_template(self, file_path: str):
        """Generates an Excel import template with sample columns."""
        df = pd.DataFrame(columns=["Name", "PAN", "DOB", "Password"])
        df.loc[0] = ["John Doe", "AAAPT0001A", "01-01-1980", "YourPortalPassword"]

        if file_path.endswith('.xlsx'):
            df.to_excel(file_path, index=False)
        elif file_path.endswith('.csv'):
            df.to_csv(file_path, index=False)
        else:
            df.to_excel(file_path + ".xlsx", index=False)

    def export_data(self, file_path: str):
        """Exports all saved assessees (with decrypted passwords) to Excel or CSV."""
        assessees = self.get_all_assessees()
        rows = [
            {
                "Name": a.get("name", ""),
                "PAN": a.get("pan", ""),
                "DOB": a.get("dob", ""),
                "Password": a.get("password", ""),
            }
            for a in assessees
        ]
        df = pd.DataFrame(rows, columns=["Name", "PAN", "DOB", "Password"])
        if file_path.endswith('.csv'):
            df.to_csv(file_path, index=False)
        else:
            df.to_excel(file_path, index=False)

    # --- Settings Management ---

    def get_setting(self, key: str, default=None):
        raw_data = self._get_raw()
        return raw_data.get("settings", {}).get(key, default)

    def update_setting(self, key: str, value):
        raw_data = self._get_raw()
        raw_data["settings"][key] = value
        self._save_raw(raw_data)
