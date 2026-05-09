"""Importer tests (no network)."""
from app.services.importer import get_importer_for
from app.services.importer.generic import GenericImporter
from app.services.importer.willhaben import WillhabenImporter


SAMPLE_HTML = """
<!doctype html>
<html><head>
  <meta property="og:title" content="Schöne 2-Zimmer Wohnung">
  <meta property="og:description" content="Helles Apartment mit Balkon">
  <meta property="og:image" content="https://example.com/img1.jpg">
  <link rel="canonical" href="https://www.willhaben.at/iad/immobilien/x/123456">
  <script type="application/ld+json">
  {
    "@context":"https://schema.org",
    "@type":"Apartment",
    "name":"2-Zimmer Wohnung",
    "address":{
      "@type":"PostalAddress",
      "streetAddress":"Mariahilfer Straße 100",
      "postalCode":"1070",
      "addressLocality":"Wien"
    },
    "geo":{"@type":"GeoCoordinates","latitude":48.197,"longitude":16.343},
    "floorSize":{"@type":"QuantitativeValue","value":55},
    "numberOfRooms":2,
    "offers":{"@type":"Offer","price":"950","priceCurrency":"EUR"}
  }
  </script>
</head><body><img src="/img2.jpg"></body></html>
"""


class _Resp:
    status_code = 200
    text = SAMPLE_HTML


def test_willhaben_selected_for_willhaben_url(app):
    with app.app_context():
        url = "https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1070/foo-987654321/"
        imp = get_importer_for(url)
        assert isinstance(imp, WillhabenImporter)


def test_generic_selected_for_other_url(app):
    with app.app_context():
        imp = get_importer_for("https://example.com/listing/1")
        assert isinstance(imp, GenericImporter)


def test_generic_extracts_jsonld(app):
    with app.app_context():
        imp = GenericImporter()
        result = imp.extract("https://example.com/listing/1", SAMPLE_HTML, _Resp())
        assert result.fields.get("title")
        assert result.fields.get("city") == "Wien"
        assert result.fields.get("postal_code") == "1070"
        assert result.fields.get("price") == 950.0
        assert result.fields.get("living_area_m2") == 55.0
        assert result.fields.get("rooms") == 2.0
        assert abs(result.fields.get("lat") - 48.197) < 1e-3
        assert result.canonical_url
        assert result.image_urls  # at least og:image and the relative img2
        assert any("img1" in u for u in result.image_urls)


def test_willhaben_external_id(app):
    with app.app_context():
        imp = WillhabenImporter()
        url = "https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1070/foo-987654321/"
        result = imp.extract(url, SAMPLE_HTML, _Resp())
        assert result.platform == "willhaben"
        assert result.external_id == "987654321"
        assert result.fields.get("country") == "Austria"
