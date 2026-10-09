import csv
import io
from datetime import datetime, timezone

import pytest

from scripts.sync_sp500 import parse_constituents, sync


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters = []
        self.action = "select"

    def select(self, *args):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def is_(self, field, value):
        self.filters.append((field, None if value == "null" else value))
        return self

    def upsert(self, payload, **kwargs):
        self.action, self.payload = "upsert", payload
        return self

    def update(self, payload):
        self.action, self.payload = "update", payload
        return self

    def execute(self):
        if self.action == "upsert":
            if self.table == "companies":
                old = self.db.companies.get(self.payload["ticker"], {})
                row = {**old, **self.payload, "id": old.get("id", self.db.next_id)}
                self.db.next_id = max(self.db.next_id, row["id"] + 1)
                self.db.companies[row["ticker"]] = row
            else:
                row = next((r for r in self.db.memberships if all(
                    r[k] == self.payload[k] for k in ("company_id", "index_code", "effective_from"))), None)
                if row is None:
                    row = {"id": len(self.db.memberships) + 1}
                    self.db.memberships.append(row)
                row.update(self.payload)
            self.db.writes += 1
            return type("Response", (), {"data": [row]})()
        rows = list(self.db.companies.values()) if self.table == "companies" else self.db.memberships
        rows = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
        if self.action == "update":
            for row in rows:
                old_ticker=row.get("ticker")
                row.update(self.payload)
                if self.table=="companies" and row.get("ticker")!=old_ticker:
                    self.db.companies.pop(old_ticker)
                    self.db.companies[row["ticker"]]=row
            self.db.writes += len(rows)
        return type("Response", (), {"data": rows})()


class Db:
    def __init__(self):
        self.companies = {f"T{i:03}": {"id": i + 1, "ticker": f"T{i:03}", "is_sp500": True}
                          for i in range(500)}
        self.memberships = [{"id": i + 1, "company_id": i + 1, "index_code": "SP500",
                             "effective_from": "2026-09-19", "effective_to": None}
                            for i in range(500)]
        self.next_id = 501
        self.writes = 0

    def table(self, name):
        return Query(self, name)


def csv_for(tickers):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["Symbol", "Security", "GICS Sector", "GICS Sub-Industry"])
    writer.writeheader()
    for ticker in tickers:
        writer.writerow({"Symbol": ticker, "Security": ticker})
    return out.getvalue()


def test_observed_membership_closes_exits_and_is_idempotent():
    db = Db()
    today = datetime(2026, 9, 29, tzinfo=timezone.utc)
    source = csv_for([f"T{i:03}" for i in range(499)] + ["NEW"])
    assert sync(db, source, today) == {"active": 500, "added": 1, "removed": 1}
    assert db.companies["T499"]["is_sp500"] is False
    old = [r for r in db.memberships if r["company_id"] == 500]
    assert old[0]["effective_to"] == "2026-09-29"
    assert sync(db, source, today) == {"active": 500, "added": 0, "removed": 0}
    assert len(db.memberships) == 501
    returned = csv_for([f"T{i:03}" for i in range(500)])
    assert sync(db, returned, datetime(2026, 10, 1, tzinfo=timezone.utc)) == {
        "active": 500, "added": 1, "removed": 1}
    assert [r["effective_from"] for r in db.memberships if r["company_id"] == 500] == [
        "2026-09-19", "2026-10-01"]


def test_invalid_source_cannot_deactivate_every_company():
    db = Db()
    with pytest.raises(ValueError, match="Unexpected constituent count"):
        sync(db, csv_for(["ONLY"]), datetime(2026, 9, 29, tzinfo=timezone.utc))
    assert db.writes == 0
    assert len(parse_constituents(csv_for([f"T{i:03}" for i in range(500)]))) == 500
    with pytest.raises(ValueError, match="duplicate"):
        parse_constituents(csv_for(["A"] * 500))


def test_confirmed_symbol_change_preserves_company_id_and_membership():
    db=Db()
    old=db.companies.pop("T499")
    old.update(ticker="PSKY",cik="2041610")
    db.companies["PSKY"]=old
    source=csv_for([f"T{i:03}" for i in range(499)]+["SKYD"])
    source=source.replace("GICS Sub-Industry\r\n","GICS Sub-Industry,CIK\r\n").replace("SKYD,SKYD,,\r\n","SKYD,SKYD,,,2041610\r\n")
    result=sync(db,source,datetime(2026,10,9,tzinfo=timezone.utc))
    assert result=={"active":500,"added":0,"removed":0}
    assert db.companies["SKYD"]["id"]==500
    assert "PSKY" not in db.companies
    assert db.memberships[-1]["effective_to"] is None
    assert sync(db,source,datetime(2026,10,9,tzinfo=timezone.utc))==result


def test_symbol_change_requires_matching_issuer_before_any_write():
    db=Db()
    old=db.companies.pop("T499")
    old.update(ticker="PSKY",cik="2041610")
    db.companies["PSKY"]=old
    source=csv_for([f"T{i:03}" for i in range(499)]+["SKYD"])
    with pytest.raises(ValueError,match="CIK"):
        sync(db,source,datetime(2026,10,9,tzinfo=timezone.utc))
    assert db.writes==0


def test_removed_member_is_retained_and_confirmed_delisting_is_inactive():
    db=Db()
    old=db.companies.pop("T499")
    old.update(ticker="WBD",cik="1437107",active=True)
    db.companies["WBD"]=old
    sync(db,csv_for([f"T{i:03}" for i in range(499)]+["TWLO"]),datetime(2026,10,9,tzinfo=timezone.utc))
    assert db.companies["WBD"]["is_sp500"] is False
    assert db.companies["WBD"]["active"] is False
    assert db.companies["WBD"]["id"]==500
