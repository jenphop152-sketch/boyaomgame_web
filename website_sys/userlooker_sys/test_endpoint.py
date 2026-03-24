import requests
import sys

def test_user_lookup():
    user_id = "1383083682511716482"
    url = f"http://localhost:8001/user/{user_id}"
    
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.json()}")
        
        if response.status_code == 200:
            data = response.json()
            if data["UserId"] == user_id:
                print("SUCCESS: User found and ID matches.")
            else:
                print("FAILURE: User ID mismatch.")
        else:
            print("FAILURE: User not found or error.")
            
    except requests.exceptions.ConnectionError:
        print("FAILURE: Could not connect to server. Is it running?")

if __name__ == "__main__":
    test_user_lookup()
