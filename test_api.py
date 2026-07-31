#this is a file created by the user to test the api system by himself. It is in no case a viable test, it's only to try.
import requests

# Root of the API. The endpoints (/agents, /clock, /health) hang directly off
# this. NOTE: "/docs" is the browser documentation page, NOT an API prefix — do
# not put it here, or every request 404s.
BASE_URL = "http://127.0.0.1:8000"

# Replace this with the management/admin key provided by your dev or found in config.yaml
API_KEY = "fk_ebrsBBkgP0cRzT57UokxfOxq9dXHMLDSxhlM2AQN85M"

# The TRD specifies static API keys per agent but doesn't dictate the exact header name. 
# "X-API-Key" is standard, but you might need to change it to "Authorization": f"Bearer {API_KEY}" 
# depending on your dev's specific FastAPI security implementation.
HEADERS = {
    "X-API-Key": API_KEY
}

def test_directory():
    """Test getting the agent directory (Allowed for all roles)."""
    print("--- Testing GET /agents ---")
    try:
        response = requests.get(f"{BASE_URL}/agents", headers=HEADERS)
        if response.status_code == 200:
            print("✅ Success! Agents Directory:\n", response.json())
        elif response.status_code == 403:
            print("❌ Forbidden (403): Your API key does not have permission.")
        elif response.status_code == 401:
            print("❌ Unauthorized (401): API key is missing or invalid.")
        else:
            print(f"⚠️ Unexpected Status ({response.status_code}):", response.text)
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: Is the FastAPI server running?")

def test_clock():
    """Test reading the system clock (System/Management only)."""
    print("\n--- Testing GET /clock ---")
    try:
        response = requests.get(f"{BASE_URL}/clock", headers=HEADERS)
        if response.status_code == 200:
            print("✅ Success! Current Clock:\n", response.json())
        elif response.status_code == 403:
            print("❌ Forbidden (403): Your role cannot access the clock.")
        else:
            print(f"⚠️ Unexpected Status ({response.status_code}):", response.text)
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: Is the FastAPI server running?")

if __name__ == "__main__":
    print("Initializing API Tests...\n")
    test_directory()
    test_clock()