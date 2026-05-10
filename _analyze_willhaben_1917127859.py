"""Analyze image structure of willhaben listing 1917127859."""
import requests, json
from bs4 import BeautifulSoup

url = 'https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1190-doebling/wunderschoene-villenetage-in-absoluter-gruenruhelage-1917127859/'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
    'Accept-Language': 'de-AT,de;q=0.9',
}
resp = requests.get(url, headers=headers, timeout=20)
print(f"HTTP {resp.status_code}, {len(resp.text)} bytes")

soup = BeautifulSoup(resp.text, 'lxml')
nd = soup.find('script', id='__NEXT_DATA__')
if not nd:
    print("NO __NEXT_DATA__")
    raise SystemExit(1)

data = json.loads(nd.string)
ad = data['props']['pageProps']['advertDetails']

# --- Image structure ---
ail = ad.get('advertImageList', {})
print(f"\n=== advertImageList keys: {list(ail.keys())} ===")
print(f"  advertImage count : {len(ail.get('advertImage', []))}")
print(f"  floorPlans count  : {len(ail.get('floorPlans', []))}")

print("\n--- advertImage URLs (referenceImageUrl) ---")
for i, img in enumerate(ail.get('advertImage', [])):
    print(f"  [{i+1:2d}] {img.get('referenceImageUrl')}")

print("\n--- floorPlans URLs ---")
for i, fp in enumerate(ail.get('floorPlans', [])):
    print(f"  [{i+1}] ref={fp.get('referenceImageUrl')}  main={fp.get('mainImageUrl')}")

# --- Also check advertAttachmentList ---
aal = ad.get('advertAttachmentList', {})
print(f"\n=== advertAttachmentList keys: {list(aal.keys())} ===")
for k, v in aal.items():
    print(f"  {k}: {v}")

# --- Run through the actual importer and see what it picks ---
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import create_app
from app.services.importer.willhaben import WillhabenImporter

app = create_app()
with app.app_context():
    imp = WillhabenImporter()
    result = imp.extract(url, resp.text, resp)
    print(f"\n=== Importer result: {len(result.image_urls)} images ===")
    for i, u in enumerate(result.image_urls):
        print(f"  [{i+1:2d}] {u}")
    print(f"\naddress={result.fields.get('address')!r}")
    print(f"lat={result.fields.get('lat')}, lng={result.fields.get('lng')}")
