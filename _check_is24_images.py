"""Cross-check image counts: Apollo state pictures[] vs what the importer extracts."""
import sys, re, json, requests
from bs4 import BeautifulSoup
from PIL import Image
import io

URLS = sys.argv[1:] or [
    "https://www.immobilienscout24.at/expose/69cb8b98a9af9d4493d68287",
    "https://www.immobilienscout24.at/expose/69fd5b4374ad1b054f4b896e",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}

for url in URLS:
    print(f"\n{'='*70}")
    print(f"URL: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        continue

    soup = BeautifulSoup(resp.text, "lxml")

    # Extract Apollo state
    apollo = None
    for s in soup.find_all("script"):
        text = (s.string or "").strip()
        if "__APOLLO_STATE__" not in text:
            continue
        for line in text.split("\n"):
            m = re.match(r"window\.__APOLLO_STATE__\s*=\s*(.+)", line.strip())
            if m:
                try:
                    apollo = json.loads(m.group(1).rstrip(";"))
                except Exception:
                    pass
        break

    if not apollo:
        print("  ERROR: could not parse Apollo state")
        continue

    expose = next((v for k, v in apollo.items() if k.startswith("Expose:") and isinstance(v, dict)), None)
    if not expose:
        print("  ERROR: no Expose: key found")
        continue

    pictures = expose.get("pictures") or []
    attachments = expose.get("attachments") or []
    print(f"Apollo pictures[]:    {len(pictures)}")
    print(f"Apollo attachments[]: {len(attachments)}")

    # Fetch and check each image
    print(f"\nVerifying each picture URL:")
    ok = 0
    for i, pic in enumerate(pictures):
        pic_url = pic.get("url", "") if isinstance(pic, dict) else pic
        caption = (pic.get("caption") or "") if isinstance(pic, dict) else ""
        try:
            r = requests.get(pic_url, headers=HEADERS, timeout=10)
            img = Image.open(io.BytesIO(r.content))
            img.load()
            w, h = img.size
            is_plan = "grundriss" in caption.lower() or "plan" in caption.lower()
            tag = " [FLOOR PLAN]" if is_plan else ""
            print(f"  [{i+1:2d}] {r.status_code} {img.mode} {w}x{h} {len(r.content):6d}B{tag}  {caption[:60]}")
            ok += 1
        except Exception as e:
            print(f"  [{i+1:2d}] ERROR: {e}  url={pic_url[:80]}")

    print(f"\n  {ok}/{len(pictures)} images successfully fetched")
