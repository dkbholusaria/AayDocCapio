import sys
import os

# Add the project root to python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.ais_converter import convert_ais_json

def test():
    json_path = "testdata/Raw JSON/VikasBanga_2024-25_AIS_18062026.json"
    pan = "AFCPB9287R"
    dob = "09-07-1979"
    try:
        res = convert_ais_json(json_path, log_callback=print, pan=pan, dob=dob)
        print("Success! Output file:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
