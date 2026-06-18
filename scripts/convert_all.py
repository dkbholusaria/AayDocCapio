import os
import sys
import json

# Add the project root to python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automation.ais_converter import convert_ais_json

def get_match(filename, assessees):
    name_part = filename.split('_')[0].lower().replace(" ", "").replace("-", "")
    # Try exact normalization match first
    for ass in assessees:
        ass_name = ass["name"].lower().replace(" ", "").replace("-", "")
        if name_part in ass_name or ass_name in name_part:
            return ass
        # Fuzzy check: remove 'h' and compare (e.g. shivasisdas vs shivasishdas)
        if name_part.replace("h", "") == ass_name.replace("h", ""):
            return ass
        # Fallback names
        if "daksm" in name_part and "daksm" in ass_name:
            return ass
        if "suved" in name_part and "suved" in ass_name:
            return ass
    return None

def main():
    vault_path = "tax_vault.json"
    with open(vault_path, "r", encoding="utf-8") as f:
        vault = json.load(f)
    assessees = vault.get("assessees", [])

    raw_dir = "testdata/Raw JSON"
    files = sorted([f for f in os.listdir(raw_dir) if f.endswith(".json")])

    success_count = 0
    fail_count = 0
    skipped_count = 0

    print(f"Found {len(files)} JSON files in {raw_dir}.")
    
    for filename in files:
        file_path = os.path.join(raw_dir, filename)
        match = get_match(filename, assessees)
        if not match:
            print(f"\n[SKIP] Could not find PAN/DOB match in vault for: {filename}")
            skipped_count += 1
            continue

        # Explicitly skip SurajPrasad 2023-24 file since it belongs to old encryption
        if filename == "SurajPrasad_2023-24_AIS_14072024.json":
            print(f"\n[SKIP] SurajPrasad_2023-24_AIS_14072024.json uses legacy/old encryption.")
            skipped_count += 1
            continue

        pan = match["pan"]
        dob = match["dob"]
            
        print(f"\n[PROCESS] Converting {filename} for {match['name']} (PAN: {pan}, DOB: {dob})...")
        try:
            res = convert_ais_json(file_path, log_callback=None, pan=pan, dob=dob)
            print(f"[SUCCESS] Converted: {res}")
            success_count += 1
        except Exception as e:
            print(f"[ERROR] Failed to convert {filename}: {e}")
            import traceback
            traceback.print_exc()
            fail_count += 1

    print("\n--- Summary ---")
    print(f"Total processed: {len(files)}")
    print(f"Successful:      {success_count}")
    print(f"Failed:          {fail_count}")
    print(f"Skipped:         {skipped_count}")

if __name__ == "__main__":
    main()
