"""MCA company master data via data.gov.in's Open Government Data API (free key).

Field names vary between datasets and over time, so each field is read through a list
of aliases. Status codes (ACTV, STOF, ...) are mapped to MCA's wording.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from truecap.domain import FactSet, Ledger, SourceType, utcnow
from truecap.facts import FactKey as K

log = logging.getLogger(__name__)
API = "https://api.data.gov.in/resource/{rid}"

ALIASES: dict[str, tuple[str, ...]] = {
    "cin": ("corporate_identification_number", "cin", "company_cin"),
    "name": ("company_name", "name"),
    "status": ("company_status", "status", "company_status_for_efiling"),
    "class": ("company_class", "class_of_company"),
    "category": ("company_category", "category"),
    "sub_category": ("company_sub_category", "sub_category"),
    "registered_on": ("date_of_registration", "date_of_incorporation", "company_registration_date",
                      "registration_date"),
    "state": ("registered_state", "state"),
    "roc": ("registrar_of_companies", "roc", "company_roc_code"),
    "paid_up": ("paidup_capital", "paid_up_capital", "paidupcapital"),
    "address": ("registered_office_address", "company_address", "address"),
    "activity": ("principal_business_activity_as_per_cin", "principal_business_activity", "company_industrial_classification"),
    "latest_bs": ("latest_year_bs", "date_of_last_balance_sheet", "last_balance_sheet_date"),
    "latest_ar": ("latest_year_ar", "date_of_last_agm", "last_agm_date"),
}

STATUS_CODES = {
    "ACTV": "Active", "ACTIVE": "Active",
    "STOF": "Strike Off", "STRIKE OFF": "Strike Off",
    "UPSO": "Under process of Striking Off",
    "AMAL": "Amalgamated", "DISD": "Dissolved", "LIQD": "Liquidated", "ULQD": "Under Liquidation",
    "DRMT": "Dormant", "DORMANT": "Dormant", "CLLP": "Converted to LLP", "CLLD": "Converted to LLP and Dissolved",
    "NAEF": "Not available for e-filing",
}


@dataclass
class RegistryRecord:
    cin: str
    name: str
    raw: dict[str, Any]
    url: str

    def get(self, field: str) -> Any:
        return _get(self.raw, field)

    @property
    def status(self) -> str | None:
        s = self.get("status")
        return STATUS_CODES.get(str(s).strip().upper(), str(s).strip().title()) if s else None

    @property
    def state(self) -> str | None:
        return self.get("state")


def _get(raw: dict[str, Any], field: str) -> Any:
    lowered = {k.lower().strip(): v for k, v in raw.items()}
    for alias in ALIASES[field]:
        v = lowered.get(alias)
        if v not in (None, "", "NA", "-"):
            return v
    return None


_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y", "%d-%m-%y")


def parse_any_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    s = str(value).strip()
    day = s.split()[0].split("T")[0]  # drop any time part
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(day, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.fullmatch(r"(?:FY)?\s*(\d{4})", s, re.I)
    if m:  # a bare year means the financial year ending 31 March of that year
        return date(int(m.group(1)), 3, 31)
    return None


def normalise_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9 ]+", " ", name.upper())
    n = re.sub(r"\b(PRIVATE|PVT|LIMITED|LTD|LLP|OPC|INDIA)\b", " ", n)
    return " ".join(n.split())


class RegistryClient:
    def __init__(self, api_key: str | None, resource_ids: list[str], http: httpx.Client) -> None:
        self.api_key = api_key
        self.resource_ids = [r.strip() for r in resource_ids if r.strip()]
        self.http = http

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.resource_ids)

    def _query(self, filters: dict[str, str], limit: int = 10) -> list[RegistryRecord]:
        out: list[RegistryRecord] = []
        for rid in self.resource_ids:
            params = {"api-key": self.api_key, "format": "json", "limit": str(limit)}
            params.update({f"filters[{k}]": v for k, v in filters.items()})
            url = API.format(rid=rid)
            try:
                resp = self.http.get(url, params=params)
                resp.raise_for_status()
                records = resp.json().get("records", [])
            except (httpx.HTTPError, ValueError) as e:
                log.warning("data.gov.in query failed for %s: %s", rid, e)
                continue
            for raw in records:
                cin, name = _get(raw, "cin"), _get(raw, "name")
                if cin and name:
                    out.append(RegistryRecord(cin=str(cin).strip().upper(), name=str(name).strip(), raw=raw,
                                              url=f"https://data.gov.in/resource/{rid}"))
        return out

    def by_cin(self, cin: str) -> RegistryRecord | None:
        if not self.enabled:
            return None
        for field in ("CORPORATE_IDENTIFICATION_NUMBER", "CIN"):
            hits = self._query({field: cin.upper()}, limit=1)
            if hits:
                return hits[0]
        return None

    def search(self, name: str) -> list[RegistryRecord]:
        """Exact-name lookups for common suffix variants (the OGD API has no fuzzy search)."""
        if not self.enabled:
            return []
        base = name.upper().strip()
        stem = re.sub(r"\s+(PRIVATE LIMITED|PVT\.? LTD\.?|LIMITED|LTD\.?)$", "", base)
        variants = dict.fromkeys([base, f"{stem} PRIVATE LIMITED", f"{stem} LIMITED"])
        seen: dict[str, RegistryRecord] = {}
        for v in variants:
            for rec in self._query({"COMPANY_NAME": v}):
                seen.setdefault(rec.cin, rec)
        return list(seen.values())


def add_registry_facts(rec: RegistryRecord, ledger: Ledger, facts: FactSet) -> None:
    """Map a registry record to facts. These are official-source facts (no LLM involved)."""
    summary = "; ".join(f"{k}: {v}" for k, v in rec.raw.items() if v not in (None, ""))[:1500]
    e = ledger.add(f"MCA company master data for {rec.name} (via data.gov.in)", SourceType.MCA,
                   url=rec.url, title="Company Master Data, Ministry of Corporate Affairs", excerpt=summary,
                   fetched_at=utcnow())
    facts.put(K.COMPANY_NAME, rec.name, e.id)
    facts.put(K.CIN, rec.cin, e.id)
    if rec.status:
        facts.put(K.STATUS, rec.status, e.id)
    reg = parse_any_date(rec.get("registered_on"))
    if reg:
        facts.put(K.INCORPORATION_DATE, reg.isoformat(), e.id)
    kind = " / ".join(str(x) for x in (rec.get("class"), rec.get("category"), rec.get("sub_category")) if x)
    if kind:
        facts.put(K.COMPANY_TYPE, kind, e.id)
    if rec.get("address"):
        facts.put(K.REGISTERED_OFFICE, str(rec.get("address")).strip(), e.id)
    paid = rec.get("paid_up")
    if paid not in (None, ""):
        try:
            facts.put(K.PAID_UP_CAPITAL, int(float(str(paid).replace(",", ""))), e.id)
        except ValueError:
            log.info("unparseable paid-up capital %r", paid)
    last = parse_any_date(rec.get("latest_bs")) or parse_any_date(rec.get("latest_ar"))
    if last:
        facts.put(K.LAST_FILING_DATE, last.isoformat(), e.id)
