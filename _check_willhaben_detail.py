"""Check description section labels and address quality for specific listings."""
import sys, os, re, json, io
sys.path.insert(0, os.path.dirname(__file__))
import requests
from bs4 import BeautifulSoup
from app import create_app
from app.services.importer.willhaben import WillhabenImporter

URLS = [
    # These two show district-only addresses - verify what Willhaben actually sends
    "https://www.willhaben.at/iad/object?adId=962278032",
    "https://www.willhaben.at/iad/object?adId=1527269794",
    # This one has lots of description sections - verify all are included
    "https://www.willhaben.at/iad/object?adId=1309776591",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}

app = create_app()
with app.app_context():
    imp = WillhabenImporter()
    for url in URLS:
        print(f"\n{'='*70}")
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        print(f"URL: {resp.url}")

        nd = json.loads(BeautifulSoup(resp.text, "lxml").find("script", id="__NEXT_DATA__").string)
        ad = nd["props"]["pageProps"]["advertDetails"]

        # --- Address ---
        aad = ad.get("advertAddressDetails") or {}
        lines = (aad.get("addressLines") or {}).get("value") or []
        print(f"\nRaw addressLines: {lines}")
        print(f"postCode: {aad.get('postCode')}  province: {aad.get('province')}  country: {aad.get('country')}")

        # --- All attribute names present ---
        attrs = {r["name"]: (r.get("values") or [""])[0]
                 for r in (ad.get("attributes", {}).get("attribute") or [])
                 if r.get("name")}
        print(f"\nAll attribute names in payload:")
        for name, val in attrs.items():
            preview = str(val)[:80].replace("\n", " ")
            print(f"  {name:45s} = {preview}")

        # --- Importer result ---
        result = imp.extract(resp.url, resp.text, resp)
        print(f"\nImporter address fields:")
        for k in ("address", "postal_code", "city", "country", "lat", "lng"):
            if result.fields.get(k) is not None:
                print(f"  {k}: {result.fields[k]}")

        # --- Full description with section breaks ---
        desc = result.fields.get("description") or ""
        print(f"\nFull description ({len(desc)} chars):")
        # Show up to 1500 chars with newlines visible
        for line in desc[:1500].split("\n"):
            print(f"  | {line}")
        if len(desc) > 1500:
            print(f"  ... ({len(desc)-1500} more chars)")
