#!/usr/bin/env python3
"""Fetch HR-related updates for Global HR Hub.

Version 2.1 design:
- Each country is fetched independently.
- A failure in one country does not stop other countries.
- If a country fails, the script keeps that country's previous successful data.
- The output includes per-country sourceStatus so the page can show Updated / No new update / Fetch failed.

This is a monitoring helper, not legal advice. HR should review source items
before taking compliance action.
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

HR_JSON_PATH = DATA_DIR / "hr-updates.json"

VISIBLE_COUNTRIES = [
    "United States",
    "Mexico",
    "Czech Republic",
    "China",
    "Taiwan",
    "Vietnam",
    "India",
    "Singapore",
]

WINDOW_DAYS = 45
MAX_ITEMS_PER_COUNTRY = 8
REQUEST_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; GlobalHRHubBot/2.1; +https://github.com/)"

BASE_KEYWORDS = [
    "labor law", "labour law", "employment", "minimum wage", "social insurance",
    "pension", "provident fund", "payroll", "tax", "government notice",
    "work permit", "overtime", "leave"
]

LOCAL_KEYWORDS = {
    "Taiwan": ["勞動部", "勞動法", "勞基法", "基本工資", "勞保", "勞退", "就業服務", "資遣", "公告"],
    "China": ["人力資源", "社會保障", "最低工資", "社保", "個人所得稅", "勞動", "公告"],
    "Vietnam": ["labor", "minimum wage", "social insurance", "tax", "payroll", "work permit"],
    "India": ["EPF", "ESIC", "labour code", "minimum wage", "provident fund", "TDS", "payroll"],
    "Singapore": ["MOM", "CPF", "IRAS", "employment act", "minimum wage", "payroll", "work pass"],
    "Mexico": ["salario mínimo", "IMSS", "SAT", "STPS", "trabajo", "seguridad social", "nómina"],
    "Czech Republic": ["labour", "employment", "minimum wage", "social security", "tax", "payroll", "zaměstnanost", "minimální mzda"],
    "United States": ["Wisconsin labor", "DWD Wisconsin", "DOL", "minimum wage", "payroll tax", "employment law", "unemployment insurance"],
}

SOURCES = {
    "Taiwan": {
        "locale": ("zh-TW", "TW", "TW:zh-Hant"),
        "domains": [
            {"domain": "mol.gov.tw", "unit": "勞動部"},
            {"domain": "wda.gov.tw", "unit": "勞動力發展署"},
            {"domain": "bli.gov.tw", "unit": "勞保局"},
        ],
    },
    "India": {
        "locale": ("en-IN", "IN", "IN:en"),
        "domains": [
            {"domain": "labour.gov.in", "unit": "Ministry of Labour & Employment"},
            {"domain": "epfindia.gov.in", "unit": "EPFO"},
            {"domain": "esic.gov.in", "unit": "ESIC"},
            {"domain": "incometax.gov.in", "unit": "Income Tax Department"},
        ],
    },
    "Vietnam": {
        "locale": ("en", "VN", "VN:en"),
        "domains": [
            {"domain": "molisa.gov.vn", "unit": "MOLISA"},
            {"domain": "baohiemxahoi.gov.vn", "unit": "Vietnam Social Security"},
            {"domain": "gdt.gov.vn", "unit": "General Department of Taxation"},
        ],
    },
    "Singapore": {
        "locale": ("en-SG", "SG", "SG:en"),
        "domains": [
            {"domain": "mom.gov.sg", "unit": "Ministry of Manpower"},
            {"domain": "cpf.gov.sg", "unit": "CPF Board"},
            {"domain": "iras.gov.sg", "unit": "IRAS"},
        ],
    },
    "China": {
        "locale": ("zh-CN", "CN", "CN:zh-Hans"),
        "domains": [
            {"domain": "mohrss.gov.cn", "unit": "MOHRSS"},
            {"domain": "chinatax.gov.cn", "unit": "State Taxation Administration"},
        ],
    },
    "Mexico": {
        "locale": ("es-MX", "MX", "MX:es-419"),
        "domains": [
            {"domain": "stps.gob.mx", "unit": "STPS"},
            {"domain": "imss.gob.mx", "unit": "IMSS"},
            {"domain": "sat.gob.mx", "unit": "SAT"},
        ],
    },
    "Czech Republic": {
        "locale": ("en", "CZ", "CZ:en"),
        "domains": [
            {"domain": "mpsv.cz", "unit": "Ministry of Labour and Social Affairs"},
            {"domain": "cssz.cz", "unit": "Czech Social Security Administration"},
            {"domain": "financnisprava.gov.cz", "unit": "Financial Administration"},
        ],
    },
    "United States": {
        "locale": ("en-US", "US", "US:en"),
        "domains": [
            {"domain": "dwd.wisconsin.gov", "unit": "Wisconsin DWD"},
            {"domain": "dol.gov", "unit": "U.S. Department of Labor"},
            {"domain": "irs.gov", "unit": "IRS"},
        ],
    },
}

CATEGORY_KEYWORDS = {
    "Minimum Wage": ["minimum wage", "basic wage", "lowest wage", "基本工資", "最低工資", "salario mínimo", "mức lương tối thiểu", "minimální mzda"],
    "Social Insurance / EPF / ESIC": ["social insurance", "insurance", "pension", "provident fund", "epf", "epfo", "esic", "cpf", "勞保", "勞退", "社會保險", "社保", "imss", "seguridad social", "bảo hiểm xã hội", "cssz"],
    "Tax / Payroll": ["tax", "payroll", "income tax", "withholding", "tds", "iras", "sat", "irs", "稅", "個人所得稅", "薪資", "thuế", "nómina"],
    "Labor Law": ["labor", "labour", "employment", "overtime", "leave", "working hours", "work permit", "勞動", "勞基法", "就業", "trabajo", "zaměstnanost"],
    "Government Notices": ["notice", "announcement", "circular", "公告", "通知", "press release", "news", "政府"],
}

@dataclass
class UpdateItem:
    country: str
    title: str
    url: str
    date: str
    published_at: Optional[datetime]
    source: str
    source_domain: str
    category: str
    summary: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def load_json(path: Path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARN: unable to read {path}: {exc}", file=sys.stderr)
    return fallback


def category_for(text: str) -> str:
    lower = text.lower()
    for category, words in CATEGORY_KEYWORDS.items():
        if any(word.lower() in lower for word in words):
            return category
    return "Government Notices"


def google_news_url(query: str, locale: tuple[str, str, str]) -> str:
    hl, gl, ceid = locale
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl={quote_plus(hl)}&gl={quote_plus(gl)}&ceid={quote_plus(ceid)}"
    )


def fetch_url(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return resp.read()


def parse_rss(xml_bytes: bytes, country: str, source_domain: str, source_unit: str) -> List[UpdateItem]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    items: List[UpdateItem] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    for node in root.findall(".//item"):
        title = clean_text(node.findtext("title"))
        link = clean_text(node.findtext("link"))
        description = clean_text(node.findtext("description"))
        pub_raw = clean_text(node.findtext("pubDate"))
        source = clean_text(node.findtext("source")) or source_unit
        published = None
        date_text = ""

        if pub_raw:
            try:
                published = parsedate_to_datetime(pub_raw)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                published = published.astimezone(timezone.utc)
                date_text = published.date().isoformat()
            except Exception:
                published = None

        if published and published < cutoff:
            continue

        combined = f"{title} {description} {source} {source_domain}"
        category = category_for(combined)
        summary = description[:220] if description else source_unit

        if not title or not link:
            continue

        items.append(UpdateItem(
            country=country,
            title=title,
            url=link,
            date=date_text,
            published_at=published,
            source=source_unit if source == source_domain else source,
            source_domain=source_domain,
            category=category,
            summary=summary,
        ))

    return items


def country_queries(country: str, source_domain: str) -> Iterable[str]:
    keywords = LOCAL_KEYWORDS.get(country, []) + BASE_KEYWORDS
    seen = set()
    for keyword in keywords:
        query = f"site:{source_domain} {keyword}"
        if query not in seen:
            seen.add(query)
            yield query


def collect_country(country: str, cfg: dict) -> Tuple[List[UpdateItem], Dict[str, int]]:
    all_items: List[UpdateItem] = []
    stats = {"queries": 0, "queryFailures": 0, "domains": len(cfg.get("domains", []))}
    locale = cfg["locale"]

    for source in cfg["domains"]:
        domain = source["domain"]
        unit = source["unit"]
        for query in country_queries(country, domain):
            stats["queries"] += 1
            url = google_news_url(query, locale)
            try:
                xml_bytes = fetch_url(url)
                all_items.extend(parse_rss(xml_bytes, country, domain, unit))
                time.sleep(0.35)
            except Exception as exc:
                stats["queryFailures"] += 1
                print(f"WARN: failed query | {country} | {domain} | {query} | {exc}", file=sys.stderr)

    # Deduplicate by normalized title + source domain.
    dedup: Dict[str, UpdateItem] = {}
    for item in all_items:
        key = re.sub(r"\W+", "", (item.title + item.source_domain).lower())[:180]
        if key not in dedup:
            dedup[key] = item

    results = list(dedup.values())
    results.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return results[:MAX_ITEMS_PER_COUNTRY], stats


def to_hr_json_item(item: UpdateItem) -> dict:
    return {
        "date": item.date,
        "type": item.category,
        "title": item.title,
        "desc": item.summary,
        "url": item.url,
        "source": item.source,
        "sourceDomain": item.source_domain,
        "isNew": True,
    }


def previous_country_items(previous_payload: dict, country: str) -> List[dict]:
    sites = previous_payload.get("sites", {}) if isinstance(previous_payload, dict) else {}
    items = sites.get(country, [])
    return items if isinstance(items, list) else []


def previous_status(previous_payload: dict, country: str) -> dict:
    status = previous_payload.get("sourceStatus", {}) if isinstance(previous_payload, dict) else {}
    value = status.get(country, {})
    return value if isinstance(value, dict) else {}


def collect_country_safe(country: str, cfg: dict, previous_payload: dict) -> tuple[List[dict], dict, Optional[List[UpdateItem]]]:
    checked_at = now_iso()
    old_status = previous_status(previous_payload, country)

    try:
        items, stats = collect_country(country, cfg)
        json_items = [to_hr_json_item(item) for item in items]
        message = "Updated" if json_items else "No new update detected"
        return json_items, {
            "ok": True,
            "message": message,
            "lastCheckedAt": checked_at,
            "lastSuccessAt": checked_at,
            "itemCount": len(json_items),
            "queries": stats.get("queries", 0),
            "queryFailures": stats.get("queryFailures", 0),
            "domains": stats.get("domains", 0),
        }, items
    except Exception as exc:
        # This should be rare because query-level errors are already caught.
        # Keep old country data so the page does not go blank.
        print(f"ERROR: country fetch failed | {country} | {exc}", file=sys.stderr)
        kept_items = previous_country_items(previous_payload, country)
        return kept_items, {
            "ok": False,
            "message": f"Fetch failed; kept previous data. {type(exc).__name__}: {str(exc)[:160]}",
            "lastCheckedAt": checked_at,
            "lastSuccessAt": old_status.get("lastSuccessAt", ""),
            "itemCount": len(kept_items),
        }, None


def taiwan_unit_from_item(item: UpdateItem) -> str:
    if "wda" in item.source_domain:
        return "勞動力發展署"
    if "bli" in item.source_domain:
        return "勞保局"
    if "mol" in item.source_domain:
        return "勞動部"
    return item.source or "勞動部"


def write_outputs(sites: Dict[str, List[dict]], statuses: Dict[str, dict], taiwan_items: Optional[List[UpdateItem]]) -> None:
    generated_at = now_iso()
    payload = {
        "generatedAt": generated_at,
        "windowDays": WINDOW_DAYS,
        "note": "Generated by GitHub Actions. Review source links before HR compliance action.",
        "sourceStatus": statuses,
        "sites": {country: sites.get(country, []) for country in VISIBLE_COUNTRIES},
    }
    HR_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Taiwan important notices are maintained by the existing Taiwan news workflow/data.
    # This Global HR Hub job only updates data/hr-updates.json to avoid overwriting
    # data/taiwan_news.json used by other pages.


def main() -> int:
    previous_payload = load_json(HR_JSON_PATH, {})
    sites: Dict[str, List[dict]] = {}
    statuses: Dict[str, dict] = {}
    latest_taiwan_items: Optional[List[UpdateItem]] = None

    for country in VISIBLE_COUNTRIES:
        cfg = SOURCES[country]
        print(f"Collecting {country}...")
        country_items, country_status, raw_items = collect_country_safe(country, cfg, previous_payload)
        sites[country] = country_items
        statuses[country] = country_status
        print(f"  status={country_status.get('message')} items={len(country_items)} failures={country_status.get('queryFailures', 0)}")
        if country == "Taiwan" and raw_items is not None:
            latest_taiwan_items = raw_items

    write_outputs(sites, statuses, latest_taiwan_items)

    failed_countries = [country for country, status in statuses.items() if not status.get("ok")]
    if failed_countries:
        print("WARN: failed countries kept previous data: " + ", ".join(failed_countries), file=sys.stderr)

    # Always exit 0 so one country's failure will not block other countries' updates.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
