"""Income Tax challans only offer clients with a PAN password (B-30)."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

from vault import VaultManager


def _seed(vault):
    vault.add_update_assessee("Sample Deductor", "ABCD12345E", "", "",
                              tds_username="tdsu", tds_password="tdsp",
                              enable_income_tax=False, enable_gst=False,
                              enable_tds=True)
    vault.add_update_assessee("GST Only Trader", "", "", "",
                              gst_username="gstuser1", gst_password="gstpass1",
                              enable_income_tax=False, enable_gst=True,
                              enable_tds=False)
    vault.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980",
                              "testpass", enable_income_tax=True,
                              enable_gst=False, enable_tds=False)


def test_challan_row_picker_lists_only_income_tax_clients():
    app = QApplication.instance() or QApplication([])
    from ui.dialogs import ChallanRowDetailDialog

    with tempfile.TemporaryDirectory() as tmp:
        vault = VaultManager(vault_path=os.path.join(tmp, "v.json"))
        _seed(vault)

        dlg = ChallanRowDetailDialog(None, vault)
        try:
            data = [dlg._pan_combo.itemData(i)
                    for i in range(dlg._pan_combo.count())]
            assert data == ["AABCP1234F"]

            texts = [dlg._pan_combo.itemText(i)
                     for i in range(dlg._pan_combo.count())]
            assert all("Sample Client" in t for t in texts)
            assert not any("Deductor" in t or "GST Only" in t for t in texts)
        finally:
            dlg.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    test_challan_row_picker_lists_only_income_tax_clients()
    print("ok")
