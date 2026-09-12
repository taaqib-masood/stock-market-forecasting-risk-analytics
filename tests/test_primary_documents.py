import hashlib
import json

import pytest

from src.reliability.primary_documents import PrimaryDocumentAcquirer, PrimaryDocumentError


PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"


class Response:
    def __init__(self, content, status=200, content_type="application/pdf"):
        self.content = content
        self.status_code = status
        self.headers = {"content-type": content_type}


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def test_primary_document_acquirer_retains_bse_pdf_and_catalogues(tmp_path):
    url = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/result.pdf"
    result = PrimaryDocumentAcquirer(tmp_path, client=Client([Response(PDF)]), retries=1).acquire(url)

    assert result.status == "downloaded"
    assert result.sha256 == hashlib.sha256(PDF).hexdigest()
    assert result.path.read_bytes() == PDF
    assert json.loads((tmp_path / "source-catalogue.jsonl").read_text().splitlines()[-1])["status"] == "downloaded"


def test_primary_document_acquirer_uses_cache(tmp_path):
    client = Client([Response(PDF)])
    acquirer = PrimaryDocumentAcquirer(tmp_path, client=client, retries=1)
    url = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/result.pdf"

    assert acquirer.acquire(url).status == "downloaded"
    assert acquirer.acquire(url).status == "cached"
    assert client.calls == 1


@pytest.mark.parametrize("url,response", [
    ("https://evil.test/result.pdf", Response(PDF)),
    ("https://www.bseindia.com/xml-data/corpfiling/AttachHis/result.pdf",
     Response(b"<html>blocked</html>", content_type="text/html")),
    ("https://www.bseindia.com/xml-data/corpfiling/AttachHis/result.pdf", Response(b"not pdf")),
])
def test_primary_document_acquirer_rejects_untrusted_or_invalid_content(tmp_path, url, response):
    with pytest.raises(PrimaryDocumentError):
        PrimaryDocumentAcquirer(tmp_path, client=Client([response]), retries=1).acquire(url)
