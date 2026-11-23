"""Tests for GST credentials in the client vault (F-20)."""
import csv
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vault import VaultManager, credential_sources


def _vault(tmp):
    return VaultManager(vault_path=os.path.join(tmp, "v.json"))


def test_gst_credentials_saved_and_read_back():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        v.add_update_assessee("Sample Pvt Ltd", "AABCP1234F", "01-01-1980", "testpass",
                              gst_username="GSTLOGIN01", gst_password="Gst@test")
        c = v.get_all_assessees()[0]
        assert c["gst_username"] == "GSTLOGIN01"
        assert c["gst_password"] == "Gst@test"
        assert c["password"] == "testpass"


def test_gst_password_is_encrypted_at_rest():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "v.json")
        v = VaultManager(vault_path=path)
        v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980", "testpass",
                              gst_username="u1", gst_password="SecretGst@test")
        raw = open(path).read()
        assert "SecretGst@test" not in raw
        assert "gst_password_enc" in raw


def test_update_keeps_gst_when_unrelated_field_changes():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        cid = v.add_update_assessee("Name One", "AABCP1234F", "01-01-1980", "testpass",
                                    gst_username="u1", gst_password="Gst@test2")
        v.add_update_assessee("Name Two", "AABCP1234F", "01-01-1980", "testpass",
                              assessee_id=cid, gst_username="u1", gst_password="Gst@test2")
        c = v.get_all_assessees()[0]
        assert c["name"] == "Name Two"
        assert c["gst_username"] == "u1"
        assert c["gst_password"] == "Gst@test2"


def test_clearing_gst_credentials():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        cid = v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980", "testpass",
                                    gst_username="u1", gst_password="Gst@test2")
        v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980", "testpass",
                              assessee_id=cid, gst_username="", gst_password="")
        c = v.get_all_assessees()[0]
        assert c["gst_username"] == ""
        assert c["gst_password"] == ""


def test_legacy_record_without_gst_fields():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "v.json")
        v = VaultManager(vault_path=path)
        raw = json.load(open(path))
        raw["key_check"] = v.encrypt_password("automated_tax_app_key")
        raw["assessees"] = [{
            "id": "legacy-1", "name": "Old Client", "pan": "AABCP1234F",
            "id_type": "PAN", "dob": "01-01-1980",
            "password_enc": v.encrypt_password("oldpass"),
            "email": "", "cc": "", "group": "", "credential_invalid": False,
        }]
        json.dump(raw, open(path, "w"))
        c = v.get_all_assessees()[0]
        assert c["gst_username"] == ""
        assert c["gst_password"] == ""
        # and can be filled in later without losing the ITD password
        v.add_update_assessee("Old Client", "AABCP1234F", "01-01-1980", "oldpass",
                              assessee_id="legacy-1", gst_username="newu",
                              gst_password="newp")
        c = v.get_all_assessees()[0]
        assert c["password"] == "oldpass"
        assert c["gst_username"] == "newu"


def test_csv_import_with_gst_columns():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        path = os.path.join(tmp, "clients.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Name", "Group", "PAN", "DOB", "Password", "Email", "CC",
                        "GST Username", "GST Password"])
            w.writerow(["With GST", "", "AABCP1234F", "01-01-1980", "testpass1", "", "",
                        "gstuser", "gstpass"])
            w.writerow(["No GST", "", "AABCP1235G", "02-02-1981", "testpass2", "", "", "", ""])
        added, updated, errors = v.import_bulk(path)
        assert (added, updated, errors) == (2, 0, [])
        by_pan = {c["pan"]: c for c in v.get_all_assessees()}
        assert by_pan["AABCP1234F"]["gst_username"] == "gstuser"
        assert by_pan["AABCP1234F"]["gst_password"] == "gstpass"
        assert by_pan["AABCP1235G"]["gst_username"] == ""


def test_csv_import_without_gst_columns_still_works():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        path = os.path.join(tmp, "clients.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Name", "PAN", "DOB", "Password"])
            w.writerow(["Legacy", "AABCP1236H", "03-03-1982", "testpass3"])
        added, updated, errors = v.import_bulk(path)
        assert (added, errors) == (1, [])
        assert v.get_all_assessees()[0]["gst_username"] == ""


def test_export_import_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        v.add_update_assessee("Ab Client", "AABCP1234F", "01-01-1980", "testpass1",
                              gst_username="u1", gst_password="g1")
        out = os.path.join(tmp, "export.csv")
        v.export_data(out)
        headers = next(csv.reader(open(out)))
        assert "GST Username" in headers and "GST Password" in headers

        v2 = VaultManager(vault_path=os.path.join(tmp, "v2.json"))
        added, updated, errors = v2.import_bulk(out)
        assert (added, errors) == (1, [])
        c = v2.get_all_assessees()[0]
        assert (c["gst_username"], c["gst_password"]) == ("u1", "g1")
        assert c["password"] == "testpass1"


def test_xlsx_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980", "testpass1",
                              gst_username="ux", gst_password="gx")
        out = os.path.join(tmp, "export.xlsx")
        v.export_data(out)
        v2 = VaultManager(vault_path=os.path.join(tmp, "v2.json"))
        added, updated, errors = v2.import_bulk(out)
        assert errors == []
        assert len(v2.get_all_assessees()) == 1
        c = v2.get_all_assessees()[0]
        assert (c["gst_username"], c["gst_password"]) == ("ux", "gx")


def test_template_contains_gst_columns():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        for name in ("template.csv", "template.xlsx"):
            path = os.path.join(tmp, name)
            v.generate_template(path)
            assert os.path.exists(path)
        assert "GST Username" in open(os.path.join(tmp, "template.csv")).readline()
        from openpyxl import load_workbook
        wb = load_workbook(os.path.join(tmp, "template.xlsx"))
        headers = [c.value for c in wb["Clients"][1]]
        assert "GST Username" in headers and "GST Password" in headers


# ── Enable flags: which portal flows a client belongs to (F-23) ─────────────

def test_gst_only_client_needs_no_pan_or_password():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        v.add_update_assessee("GST Only Trader", "", "", "",
                              gst_username="gstuser1", gst_password="gstpass1",
                              enable_income_tax=False, enable_gst=True,
                              enable_tds=False)
        c = v.get_all_assessees()[0]
        assert c["pan"] == ""
        assert c["password"] == ""
        assert credential_sources(c) == ["GST"]


def test_tds_only_client_is_tagged_tds_and_nothing_else():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        v.add_update_assessee("Sample Deductor", "ABCD12345E", "", "",
                              tds_username="tdsu", tds_password="tdsp",
                              enable_income_tax=False, enable_gst=False,
                              enable_tds=True)
        c = v.get_all_assessees()[0]
        assert credential_sources(c) == ["TDS"]


def test_disabling_a_portal_removes_it_from_the_lists():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        cid = v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980",
                                    "testpass", gst_username="gu",
                                    gst_password="gp", enable_income_tax=True,
                                    enable_gst=True, enable_tds=False)
        assert credential_sources(v.get_all_assessees()[0]) == ["Income Tax", "GST"]
        # turn GST off but keep the stored credentials around
        v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980",
                              "testpass", assessee_id=cid, gst_username="gu",
                              gst_password="gp", enable_income_tax=True,
                              enable_gst=False, enable_tds=False)
        assert credential_sources(v.get_all_assessees()[0]) == ["Income Tax"]


def test_enable_flags_default_to_inferring_from_credentials():
    """Callers that predate the flags (imports, old code) keep working."""
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980",
                              "testpass", gst_username="gu", gst_password="gp")
        assert credential_sources(v.get_all_assessees()[0]) == ["Income Tax", "GST"]


def test_pan_without_password_rejected_when_income_tax_enabled():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        try:
            v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980", "",
                                  enable_income_tax=True)
        except ValueError as e:
            assert "password" in str(e).lower()
        else:
            raise AssertionError("income-tax client without password should fail")


def test_enable_columns_round_trip_csv():
    with tempfile.TemporaryDirectory() as tmp:
        v = _vault(tmp)
        v.add_update_assessee("GST Only Trader", "", "", "",
                              gst_username="gstuser1", gst_password="gstpass1",
                              enable_income_tax=False, enable_gst=True,
                              enable_tds=False)
        v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980",
                              "testpass", enable_income_tax=True,
                              enable_gst=False, enable_tds=False)
        out = os.path.join(tmp, "export.csv")
        v.export_data(out)
        headers = next(csv.reader(open(out)))
        assert "Enable Income Tax" in headers and "Enable GST" in headers

        v2 = VaultManager(vault_path=os.path.join(tmp, "v2.json"))
        added, updated, errors = v2.import_bulk(out)
        assert errors == []
        by_name = {c["name"]: c for c in v2.get_all_assessees()}
        assert credential_sources(by_name["GST Only Trader"]) == ["GST"]
        assert credential_sources(by_name["Sample Client"]) == ["Income Tax"]
