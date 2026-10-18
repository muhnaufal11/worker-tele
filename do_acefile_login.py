import urllib.request
import urllib.parse
import ssl
import json
import http.cookiejar

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

token = "9161a5a9434035558616d647540ab9ca050cce53045055cb08fd03ce172f2c43"
code = "http://127.0.0.1/?iss=https://accounts.google.com&code=4/0AXlqoi7pqw1qmHRvyOqxpYShmX6dfwLTHP7i493zi2jx2571lLVQrSibrOva1WzWKY3-3A&scope=email%20profile%20https://www.googleapis.com/auth/drive%20https://www.googleapis.com/auth/userinfo.profile%20https://www.googleapis.com/auth/userinfo.email%20openid&authuser=0&prompt=consent"
client_id = "rclone"
client_secret = "rclone"

login_url = "https://account.acefile.co/altlogin/login/"
authurl = f"{login_url}?token={token}&client_id={client_id}&client_secret={client_secret}&code={urllib.parse.quote(code)}"

payload = urllib.parse.urlencode({
    "client_id": client_id,
    "client_secret": client_secret,
    "token": token,
    "code": code
}).encode('utf-8')

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': f'https://account.acefile.co/altlogin/?token={token}',
    'X-Requested-With': 'XMLHttpRequest',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
}

req = urllib.request.Request(authurl, data=payload, headers=headers, method='POST')
try:
    with opener.open(req, timeout=15) as r:
        resp_data = r.read().decode('utf-8', errors='ignore')
        print("LOGIN RESPONSE:")
        print(resp_data)
        
        parsed = json.loads(resp_data)
        if not parsed.get('error') and parsed.get('redirect'):
            red_url = parsed['redirect']
            print("Following redirect to:", red_url)
            req_red = urllib.request.Request(red_url, headers=headers)
            with opener.open(req_red, timeout=15) as red_r:
                print("Redirect response status:", red_r.status)
                print("Final URL:", red_r.geturl())
                
            # Print cookies
            cookies_dict = {}
            for c in cj:
                print(f"Cookie: {c.name} = {c.value} (domain: {c.domain})")
                cookies_dict[c.name] = c.value
            
            with open('/home/naufal/Web-Anime/tools/terop-worker/.acefile_cookies.json', 'w') as f:
                json.dump(cookies_dict, f, indent=2)
            print("Saved cookies to .acefile_cookies.json successfully!")
except Exception as e:
    print("Error:", e)
