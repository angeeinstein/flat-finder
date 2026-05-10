"""Test the ImmoScout24 importer against the saved page HTML."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.services.importer.immoscout24 import ImmoScout24Importer

URL = "https://www.immobilienscout24.at/expose/69fd592474ad1b054f4b8814"

app = create_app()
with app.app_context():
    imp = ImmoScout24Importer()
    print(f"can_handle: {imp.can_handle(URL)}")

    # Use cached HTML so we don't re-fetch
    html = open("_immoscout24_page.html", encoding="utf-8").read()

    class FakeResp:
        status_code = 200
        text = html
        url = URL

    result = imp.extract(URL, html, FakeResp())

    print(f"\n=== RESULT ===")
    print(f"platform:     {result.platform}")
    print(f"external_id:  {result.external_id}")
    print(f"canonical_url:{result.canonical_url}")
    print(f"images:        {len(result.image_urls)} URLs")
    for i, u in enumerate(result.image_urls):
        print(f"  [{i+1:2d}] {u[:100]}")

    print(f"\n=== FIELDS ===")
    for k, v in sorted(result.fields.items()):
        if v is not None:
            print(f"  {k:30s} = {repr(v)[:120]}")

    print(f"\n=== DESCRIPTION (first 500 chars) ===")
    desc = result.fields.get("description") or result.text_snapshot or ""
    print(desc[:500])
