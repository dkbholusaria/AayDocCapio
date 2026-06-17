"""
AIS JSON decryptor — AES-256-CBC with PBKDF2-SHA256.

File format (confirmed against ITD AIS Utility v2024-25 downloads):
  [0:32]   32 ASCII hex chars  = AES-256-CBC IV  (16 bytes when decoded)
  [32:64]  32 ASCII hex chars  = PBKDF2 salt     (16 bytes when decoded)
  [64:]    base64 ciphertext   = AES-256-CBC / PKCS7

Password formula: pan.lower() + "GQ39%*g" + dob_ddmmyyyy
Key derivation:   PBKDF2-HMAC-SHA256, 1000 iterations, dklen=32
"""

import base64
import hashlib
import json

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def decrypt_ais_json(json_path: str, pan: str, dob: str) -> dict:
    """
    Decrypt an ITD AIS JSON file and return the parsed dict.

    pan : any case — lowercased automatically
    dob : vault format DD-MM-YYYY — hyphens stripped automatically to DDMMYYYY

    Raises ValueError on bad PKCS7 padding (wrong PAN or DOB).
    """
    with open(json_path, "rb") as f:
        raw = f.read()

    try:
        iv_bytes   = bytes.fromhex(raw[0:32].decode("ascii"))
        salt_bytes = bytes.fromhex(raw[32:64].decode("ascii"))
        ct         = base64.b64decode(raw[64:])
    except Exception as exc:
        raise ValueError(f"File does not look like an AIS JSON export: {exc}") from exc

    pw  = (pan.lower() + "GQ39%*g" + dob.replace("-", "")).encode("utf-8")
    key = hashlib.pbkdf2_hmac("sha256", pw, salt_bytes, 1000, dklen=32)

    cipher   = Cipher(algorithms.AES(key), modes.CBC(iv_bytes), backend=default_backend())
    dec      = cipher.decryptor()
    padded   = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    return json.loads(plaintext)


def ais_derive_fy(download_date: str) -> str:
    """
    Convert a downloadDate string like '23-Jul-2025' to FY label '2024-25'.
    ITD financial year ends 31-March. April download → new FY.
    """
    from datetime import datetime
    try:
        dt = datetime.strptime(download_date, "%d-%b-%Y")
    except ValueError:
        try:
            dt = datetime.strptime(download_date, "%d-%m-%Y")
        except ValueError:
            return "Unknown-FY"

    year = dt.year
    if dt.month <= 3:
        return f"{year - 1}-{str(year)[2:]}"
    else:
        return f"{year}-{str(year + 1)[2:]}"
