import urllib.request
import urllib.error

try:
    req = urllib.request.Request('http://127.0.0.1:8088/api/memory/long_term?page=1&page_size=10')
    res = urllib.request.urlopen(req, timeout=5)
    print('Status:', res.status)
    print(res.read().decode())
except urllib.error.HTTPError as e:
    print('Error Status:', e.code)
    print(e.read().decode())
except Exception as e:
    print('Exception:', e)
