"""Check why image #5 of listing 1393760638 is dropped by the pipeline."""
import io, requests
from PIL import Image

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
    'Accept-Language': 'de-AT,de;q=0.9',
}

# From our previous analysis: image #5 for listing 1393760638
img_url = 'https://cache.willhaben.at/mmo/8/139/376/0638_819521133_n.jpg'

resp = requests.get(img_url, headers=headers, timeout=15)
print(f"HTTP {resp.status_code}, {len(resp.content)} bytes")

content = resp.content
MIN_IMAGE_BYTES = 4 * 1024
print(f"MIN_IMAGE_BYTES check: {len(content)} >= {MIN_IMAGE_BYTES} ? {len(content) >= MIN_IMAGE_BYTES}")

img = Image.open(io.BytesIO(content))
img.load()
w, h = img.size
print(f"Mode: {img.mode}, Size: {w}x{h}, Format: {img.format}")

MIN_IMAGE_WIDTH = 320
MIN_IMAGE_HEIGHT = 200
print(f"Size check: w={w}>={MIN_IMAGE_WIDTH}? {w>=MIN_IMAGE_WIDTH}, h={h}>={MIN_IMAGE_HEIGHT}? {h>=MIN_IMAGE_HEIGHT}")

is_grayscale = img.mode in ("L", "1", "LA", "P")
print(f"is_grayscale: {is_grayscale}")

try:
    import imagehash
    phash = str(imagehash.phash(img.convert("RGB")))
    print(f"phash: {phash}")
except ImportError:
    print("imagehash not available")

# Also check the _looks_like_property_image filter
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.services.importer.generic import _looks_like_property_image
print(f"\n_looks_like_property_image({img_url!r}):")
print(f"  -> {_looks_like_property_image(img_url)}")

# Now check ALL 11 image URLs from that listing
print("\n=== Checking all URLs from listing 1393760638 ===")
from bs4 import BeautifulSoup
import json

url = 'https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1190-doebling/sonnige-4-zimmer-wohnung-mit-balkon-in-doebling-1393760638'
page = requests.get(url, headers=headers, timeout=20)
soup = BeautifulSoup(page.text, 'lxml')
data = json.loads(soup.find('script', id='__NEXT_DATA__').string)
ad = data['props']['pageProps']['advertDetails']
ail = ad['advertImageList']

all_urls = [img['referenceImageUrl'] for img in ail.get('advertImage', [])]
all_urls += [fp['referenceImageUrl'] for fp in ail.get('floorPlans', [])]

for i, u in enumerate(all_urls):
    r = requests.get(u, headers=headers, timeout=15)
    content = r.content
    passes_bytes = len(content) >= MIN_IMAGE_BYTES
    try:
        im = Image.open(io.BytesIO(content))
        im.load()
        iw, ih = im.size
        passes_size = iw >= MIN_IMAGE_WIDTH and ih >= MIN_IMAGE_HEIGHT
        gray = im.mode in ("L", "1", "LA", "P")
        if gray:
            passes_size = iw >= 150 and ih >= 100
        status = "OK" if (passes_bytes and passes_size) else "FILTERED"
    except Exception as e:
        iw, ih, gray, status = 0, 0, False, f"ERR:{e}"
    print(f"  [{i+1:2d}] {status:8s} {iw}x{ih} gray={gray} bytes={len(content):6d}  {u.split('/')[-1]}")
