"""
Clalit Pharmacy Search API Client
Python port of the Clalit pharmacy stock search skill.
Supports medication search, city lookup, pharmacy lookup, and stock checking.

Based on: https://github.com/tomron/agent-skill-clalit-pharm-search
"""

import base64
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

SEARCH_BASE = "https://e-services.clalit.co.il/PharmacyStockCoreAPI/Search"
LANG = "he-il"

STATUS_LABELS = {
    30: "במלאי",
    20: "מלאי מוגבל",
    0: "אין במלאי",
    10: "אין מידע",
}


def _encode_search_text(text: str) -> str:
    """Base64 encode search text (UTF-8)."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def stock_label(code: int) -> str:
    return STATUS_LABELS.get(code, f"קוד {code}")


async def _search_post(path: str, body: dict) -> list | dict | None:
    """POST to the Clalit Search API."""
    url = f"{SEARCH_BASE}/{path}?lang={LANG}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.error(f"Clalit API error: {resp.status}")
                    return None
                return await resp.json()
    except Exception as e:
        logger.error(f"Clalit API request failed: {e}")
        return None


async def search_medications(query: str) -> list[dict]:
    """Search medications by name (Hebrew or English). Returns list of {catCode, omryName}."""
    results = await _search_post("GetFilterefMedicationsList", {
        "searchText": _encode_search_text(query),
        "isPrefix": True,
    })
    if not results:
        return []
    return [{"catCode": m.get("catCode"), "omryName": m.get("omryName")} for m in results]


async def get_all_cities() -> list[dict]:
    """Get all cities with Clalit pharmacies. Returns list of {cityCode, cityName}."""
    results = await _search_post("GetAllCitiesList", {})
    if not results:
        return []
    return [{"cityCode": c.get("cityCode"), "cityName": c.get("cityName")} for c in results]


async def search_cities(query: str) -> list[dict]:
    """Search cities by name filter."""
    all_cities = await get_all_cities()
    query_lower = query.lower()
    return [c for c in all_cities if query_lower in c["cityName"].lower()]


async def search_pharmacies(query: str) -> list[dict]:
    """Search pharmacy branches by name. Returns list of {deptCode, deptName}."""
    results = await _search_post("GetFilterefPharmaciesList", {
        "searchText": _encode_search_text(query),
        "isPrefix": False,
    })
    if not results:
        return []
    return [{"deptCode": p.get("deptCode"), "deptName": p.get("deptName")} for p in results]


async def check_stock_by_city(cat_codes: list[int], city_code: int) -> Optional[dict]:
    """
    Check medication stock in a city.
    NOTE: The stock endpoint requires Puppeteer/browser automation due to WAF protection.
    This function uses the direct API which may be blocked. If blocked, returns None.
    """
    # Resolve medication names
    medications = []
    for code in cat_codes:
        meds = await search_medications(str(code))
        name = str(code)
        for m in meds:
            if m["catCode"] == code:
                name = m["omryName"]
                break
        medications.append({"catCode": code, "omryName": name})

    # Resolve city name
    cities = await get_all_cities()
    city_name = str(city_code)
    for c in cities:
        if c["cityCode"] == city_code:
            city_name = c["cityName"]
            break

    return {
        "note": "בדיקת מלאי בפועל דורשת דפדפן. להלן פרטי החיפוש:",
        "medications": medications,
        "city": {"cityCode": city_code, "cityName": city_name},
    }


async def check_stock_by_pharmacy(cat_codes: list[int], dept_code: int) -> Optional[dict]:
    """
    Check medication stock at a specific pharmacy.
    NOTE: Same WAF limitation as check_stock_by_city.
    """
    medications = []
    for code in cat_codes:
        meds = await search_medications(str(code))
        name = str(code)
        for m in meds:
            if m["catCode"] == code:
                name = m["omryName"]
                break
        medications.append({"catCode": code, "omryName": name})

    return {
        "note": "בדיקת מלאי בפועל דורשת דפדפן. להלן פרטי החיפוש:",
        "medications": medications,
        "pharmacy": {"deptCode": dept_code},
    }
