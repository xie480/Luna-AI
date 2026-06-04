import urllib.request
import json

url = "http://127.0.0.1:8088/api/chat"
data = json.dumps({"sessionId":"20260604","message":"luna","msgId":"123"}).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

try:
    print("Sending request...")
    response = urllib.request.urlopen(req, timeout=5)
    print(f"Response Status: {response.status}")
    print(f"Response Body: {response.read().decode('utf-8')}")
except Exception as e:
    print(f"Error: {e}")
