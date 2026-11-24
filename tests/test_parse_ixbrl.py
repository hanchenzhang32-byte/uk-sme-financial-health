"""Tests for the iXBRL parser, run with: python -m pytest"""
import csv
import io
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import parse_ixbrl as p  # noqa: E402

IX = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"


def fact(text, **attrs):
    attr = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return etree.fromstring(f'<ix:nonFraction xmlns:ix="{IX}" {attr}>{text}</ix:nonFraction>')


@pytest.mark.parametrize("text, attrs, expected", [
    ("1,234", {}, 1234.0),
    ("1,234", {"sign": "-"}, -1234.0),
    ("12", {"scale": "3"}, 12000.0),
    ("-", {"format": "ixt:fixed-zero"}, 0.0),
    ("-", {"format": "ixt4:fixed-dash"}, 0.0),
    ("1.234,56", {"format": "ixt:numcommadecimal"}, 1234.56),
    ("£ 5,000", {}, 5000.0),
    ("n/a", {}, None),
])
def test_parse_value(text, attrs, expected):
    assert p.parse_value(fact(text, **attrs)) == expected


def test_brackets_alone_do_not_make_a_number_negative():
    # Accounts show (1,500) for a negative figure, but only sign="-" makes it negative in iXBRL.
    # This is the source of the sign errors that sql/04_checks.sql finds.
    assert p.parse_value(fact("(1,500)")) == 1500.0
    assert p.parse_value(fact("(1,500)", sign="-")) == -1500.0


DOC = f"""<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="{IX}" xmlns:xbrli="{XBRLI}"
  xmlns:xbrldi="{XBRLDI}" xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
<body><ix:header><ix:resources>
  <xbrli:context id="c1"><xbrli:entity/><xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="c2"><xbrli:entity><xbrli:segment>
      <xbrldi:explicitMember dimension="bus:MaturitiesOrExpirationPeriodsDimension">bus:WithinOneYear</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="d1"><xbrli:entity/><xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate>
    <xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:unit id="GBP"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>
</ix:resources></ix:header>
<p><ix:nonFraction name="core:Equity" contextRef="c1" unitRef="GBP" sign="-">2,500</ix:nonFraction></p>
<p><ix:nonFraction name="core:Creditors" contextRef="c2" unitRef="GBP">10,000</ix:nonFraction></p>
<p><ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d1" unitRef="GBP">3</ix:nonFraction></p>
</body></html>"""


def test_contexts_keep_periods_and_dimensions():
    root = etree.fromstring(DOC.encode(), p.PARSER)
    ctx = p.read_contexts(root)
    assert ctx["c1"] == (None, "2026-03-31", "")
    assert ctx["c2"] == (None, "2026-03-31", "MaturitiesOrExpirationPeriodsDimension=WithinOneYear")
    assert ctx["d1"] == ("2025-04-01", "2026-03-31", "")
    assert p.read_units(root)["GBP"] == "GBP"


def test_file_name_gives_company_and_date():
    m = p.FILE_RE.search("Prod224_0067_01234567_20260331.html")
    assert m.groups() == ("01234567", "20260331")
    assert p.FILE_RE.search("not_an_account.html") is None


def test_parse_zip_end_to_end(tmp_path):
    zpath = tmp_path / "Accounts_Bulk_Data-2026-11-20.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("Prod224_0067_01234567_20260331.html", DOC)
        z.writestr("readme.txt", "not an account")
    filings, facts = io.StringIO(), io.StringIO()
    stats = Counter()
    last_id = p.parse_zip(str(zpath), csv.writer(filings), csv.writer(facts), 0, stats)
    assert last_id == 1
    assert stats["filings"] == 1 and stats["facts"] == 3 and stats["skipped_not_html"] == 1
    rows = list(csv.reader(io.StringIO(facts.getvalue())))
    by_tag = {r[1]: r for r in rows}
    assert float(by_tag["Equity"][7]) == -2500.0
    assert by_tag["Creditors"][4] == "MaturitiesOrExpirationPeriodsDimension=WithinOneYear"
    assert by_tag["AverageNumberEmployeesDuringPeriod"][2] == "2025-04-01"
    filing = next(csv.reader(io.StringIO(filings.getvalue())))
    assert filing[1:3] == ["01234567", "2026-03-31"]
