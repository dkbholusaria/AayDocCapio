"""Income Tax Download Documents lists only Income Tax clients (B-30)."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QLineEdit, QTableWidget

from vault import VaultManager


def _make_tab(vault):
    """Build the Download Documents tab against a real vault without booting
    the whole application. Reuses the real _dl_refresh_clients."""
    import types

    import app as app_mod

    app_inst = types.SimpleNamespace()
    app_inst._dl_refresh_clients = (
        app_mod.AayDocCapioApp._dl_refresh_clients.__get__(app_inst))
    app_inst.vault = vault
    app_inst.assessee_list = vault.get_all_assessees()
    app_inst._dl_table = QTableWidget()
    app_inst._dl_table.setColumnCount(4)
    app_inst._dl_search = QLineEdit()
    app_inst._dl_client_cbs = {}
    app_inst._dl_selected_ids = {a.get("id") for a in app_inst.assessee_list}
    app_inst.log = lambda *_a, **_k: None
    return app_inst


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


def test_download_tab_lists_only_income_tax_clients():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        vault = VaultManager(vault_path=os.path.join(tmp, "v.json"))
        _seed(vault)
        assert len(vault.get_all_assessees()) == 3

        tab = _make_tab(vault)
        tab._dl_refresh_clients()

        names = [tab._dl_table.item(r, 1).text()
                 for r in range(tab._dl_table.rowCount())]
        assert names == ["Sample Client"]
        assert list(tab._dl_client_cbs.keys()) == [
            a["id"] for a in vault.get_all_assessees() if a["name"] == "Sample Client"]

        # hidden GST/TDS clients are dropped from selection state too
        known_it_ids = set(tab._dl_client_cbs)
        assert tab._dl_selected_ids == known_it_ids

        tab._dl_table.deleteLater()
        tab._dl_search.deleteLater()
        app.processEvents()


def test_download_tab_all_clients_hidden_when_none_have_income_tax():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        vault = VaultManager(vault_path=os.path.join(tmp, "v.json"))
        vault.add_update_assessee("GST Only Trader", "", "", "",
                                  gst_username="gstuser1", gst_password="gstpass1",
                                  enable_income_tax=False, enable_gst=True,
                                  enable_tds=False)
        tab = _make_tab(vault)
        tab._dl_refresh_clients()
        assert tab._dl_table.rowCount() == 0
        assert tab._dl_selected_ids == set()

        tab._dl_table.deleteLater()
        tab._dl_search.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    test_download_tab_lists_only_income_tax_clients()
    test_download_tab_all_clients_hidden_when_none_have_income_tax()
    print("ok")
