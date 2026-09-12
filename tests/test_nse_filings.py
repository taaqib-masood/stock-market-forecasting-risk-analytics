import json

import pytest

from src.reliability.nse_filings import acquire_index_documents
from src.reliability.xbrl import XbrlResult


class FakeAcquirer:
    def __init__(self, path):
        self.path = path
        self.urls = []

    def acquire(self, url):
        self.urls.append(url)
        return XbrlResult("downloaded", url, self.path, "abc", self.path.stat().st_size,
                           "2024-04-20T10:00:00Z")


def test_acquire_index_documents_is_bounded_deduplicated_and_writes_facts(tmp_path):
    xbrl = tmp_path / "source.xml"
    xbrl.write_text('''<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:i="https://example.test"><context id="c"><period><instant>2024-03-31</instant>
      </period></context><i:Assets contextRef="c">100</i:Assets></xbrl>''')
    index = tmp_path / "index.json"
    url = "https://nsearchives.nseindia.com/corporate/xbrl/TCS.xml"
    index.write_text(json.dumps([
        {"symbol": "TCS", "toDate": "31-Mar-2024", "filingDate": "20-Apr-2024 15:30",
         "xbrl": url},
        {"symbol": "TCS", "toDate": "31-Mar-2024", "filingDate": "20-Apr-2024 15:30",
         "xbrl": url},
    ]))
    output = tmp_path / "facts.json"
    fake = FakeAcquirer(xbrl)

    report = acquire_index_documents(index, output, limit=1, delay_seconds=0, acquirer=fake)

    assert report["downloaded"] == 1
    assert report["failures"] == []
    assert len(fake.urls) == 1
    assert json.loads(output.read_text())[0]["symbol"] == "TCS"


def test_acquire_index_documents_requires_explicit_safe_limit(tmp_path):
    with pytest.raises(ValueError, match="limit"):
        acquire_index_documents(tmp_path / "missing.json", tmp_path / "out.json", limit=0)
