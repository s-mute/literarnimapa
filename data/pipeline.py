#!/usr/bin/env python3
"""
Wikidata → SQLite pipeline for Czech literary map.
Fetches Czech poets with birthplace data and populates mista + autori tables.

Usage:
    python data/pipeline.py [--db PATH]
"""

import argparse
import os
import sqlite3
import time
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "LiterarniMapa/1.0 (https://github.com/literarnimapa; contact@example.com)"

DB_PATH = os.path.join(os.path.dirname(__file__), "literarnimapa.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

SPARQL_QUERY = """
SELECT DISTINCT
  ?autor ?autorLabel
  ?rok_narozeni ?rok_umrti
  ?naroziste ?narozisteLabel
  ?lat ?lon
  ?sitelinks_count ?ma_cs_wiki
WHERE {
  # Czech Republic (Q213), Czechoslovakia (Q33946), Austria-Hungary (Q28513),
  # Austrian Empire (Q131964), Habsburg monarchy (Q153136),
  # Kingdom of Bohemia (Q42585), Bohemia (Q39193), Cisleithania (Q533534)
  VALUES ?stat {
    wd:Q213 wd:Q33946
    wd:Q28513 wd:Q131964 wd:Q153136
    wd:Q42585 wd:Q39193 wd:Q533534
  }
  ?autor wdt:P27  ?stat.
  ?autor wdt:P106 wd:Q49757.

  OPTIONAL { ?autor wdt:P569 ?born.  BIND(YEAR(?born) AS ?rok_narozeni) }
  OPTIONAL { ?autor wdt:P570 ?died.  BIND(YEAR(?died) AS ?rok_umrti) }

  # Require birthplace to be in the Czech Republic — filters out non-Czech authors
  # who share Habsburg-era nationality (e.g. Manzoni, Grillparzer)
  ?autor wdt:P19 ?naroziste.
  ?naroziste wdt:P17 wd:Q213.

  OPTIONAL {
    ?naroziste wdt:P625 ?coords.
    BIND(geof:latitude(?coords)  AS ?lat)
    BIND(geof:longitude(?coords) AS ?lon)
  }

  OPTIONAL { ?autor wikibase:sitelinks ?sitelinks_count. }

  OPTIONAL {
    ?csArticle schema:about ?autor ;
               schema:isPartOf <https://cs.wikipedia.org/> .
  }
  BIND(BOUND(?csArticle) AS ?ma_cs_wiki)

  SERVICE wikibase:label { bd:serviceParam wikibase:language "cs,en". }
}
"""

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def upsert_misto(conn: sqlite3.Connection, wikidata_id: str, nazev: str,
                 lat: float, lon: float) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO mista (nazev, lat, lon, wikidata_id) VALUES (?, ?, ?, ?)",
        (nazev, lat, lon, wikidata_id),
    )
    row = conn.execute(
        "SELECT id FROM mista WHERE wikidata_id = ?", (wikidata_id,)
    ).fetchone()
    return row[0]


def upsert_autor(conn: sqlite3.Connection, record: dict, misto_id: int | None) -> None:
    conn.execute(
        """INSERT INTO autori
           (jmeno, rok_narozeni, rok_umrti, naroziste_id, wikidata_id, sitelinks_count, ma_cs_wiki)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(wikidata_id) DO UPDATE SET
             sitelinks_count = excluded.sitelinks_count,
             ma_cs_wiki      = excluded.ma_cs_wiki""",
        (
            record["jmeno"],
            record["rok_narozeni"],
            record["rok_umrti"],
            misto_id,
            record["wikidata_id"],
            record["sitelinks_count"],
            record["ma_cs_wiki"],
        ),
    )

# ---------------------------------------------------------------------------
# Wikidata fetch
# ---------------------------------------------------------------------------

def fetch_poets(max_retries: int = 3) -> list[dict]:
    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": USER_AGENT,
    }
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                SPARQL_ENDPOINT,
                params={"query": SPARQL_QUERY, "format": "json"},
                headers=headers,
                timeout=60,
            )
            if resp.status_code in (429, 503):
                wait = 2 ** attempt
                print(f"[WARN] Rate limited ({resp.status_code}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["results"]["bindings"]
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Wikidata fetch failed after {max_retries} attempts: {e}") from e
            wait = 2 ** attempt
            print(f"[WARN] Request error: {e}. Retrying in {wait}s...")
            time.sleep(wait)
    return []


def parse_row(binding: dict) -> dict | None:
    def val(key: str) -> str | None:
        return binding[key]["value"] if key in binding else None

    autor_uri = val("autor")
    jmeno = val("autorLabel")
    if not jmeno or not autor_uri:
        return None

    naroziste_uri = val("naroziste")
    raw_born = val("rok_narozeni")
    raw_died = val("rok_umrti")
    raw_lat = val("lat")
    raw_lon = val("lon")

    raw_sitelinks = val("sitelinks_count")
    ma_cs_wiki = val("ma_cs_wiki")

    return {
        "wikidata_id": autor_uri.split("/")[-1],
        "jmeno": jmeno,
        "rok_narozeni": int(raw_born) if raw_born else None,
        "rok_umrti": int(raw_died) if raw_died else None,
        "naroziste_wikidata_id": naroziste_uri.split("/")[-1] if naroziste_uri else None,
        "naroziste_label": val("narozisteLabel"),
        "lat": float(raw_lat) if raw_lat else None,
        "lon": float(raw_lon) if raw_lon else None,
        "sitelinks_count": int(raw_sitelinks) if raw_sitelinks else 0,
        "ma_cs_wiki": ma_cs_wiki == "true" if ma_cs_wiki else False,
    }

# ---------------------------------------------------------------------------
# Nominatim geocoding fallback
# ---------------------------------------------------------------------------

_last_nominatim_call: float = 0.0


def geocode_nominatim(place_label: str) -> tuple[float, float] | None:
    global _last_nominatim_call
    elapsed = time.monotonic() - _last_nominatim_call
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    params = {
        "q": place_label,
        "format": "json",
        "limit": 1,
        "countrycodes": "cz",
        "accept-language": "cs",
    }
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        _last_nominatim_call = time.monotonic()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
        # Retry without country bias
        params.pop("countrycodes")
        resp = requests.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"[WARN] Nominatim failed for '{place_label}': {e}")
    return None

# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(db_path: str = DB_PATH) -> None:
    print(f"[INFO] Database: {db_path}")

    conn = sqlite3.connect(db_path)
    init_db(conn)

    # Clear existing data so stale records don't accumulate across runs
    conn.execute("DELETE FROM autori")
    conn.execute("DELETE FROM mista")
    conn.commit()
    print("[INFO] Cleared existing data")

    print("[INFO] Fetching poets from Wikidata...")
    bindings = fetch_poets()
    print(f"[INFO] Got {len(bindings)} rows from Wikidata")

    records = []
    skipped_parse = 0
    for b in bindings:
        r = parse_row(b)
        if r:
            records.append(r)
        else:
            skipped_parse += 1
    print(f"[INFO] Parsed {len(records)} records, skipped {skipped_parse} malformed")

    place_cache: dict[str, int] = {}  # naroziste_wikidata_id → mista.id
    inserted_autori = 0
    inserted_mista = 0
    nominatim_calls = 0
    no_place = 0

    conn.execute("BEGIN")
    for i, rec in enumerate(records, 1):
        if i % 50 == 0:
            print(f"[INFO] Progress: {i}/{len(records)}")

        misto_id: int | None = None
        nwid = rec["naroziste_wikidata_id"]

        if nwid:
            if nwid in place_cache:
                misto_id = place_cache[nwid]
            elif rec["lat"] and rec["lon"]:
                misto_id = upsert_misto(conn, nwid, rec["naroziste_label"] or nwid,
                                        rec["lat"], rec["lon"])
                if nwid not in place_cache:
                    inserted_mista += 1
                place_cache[nwid] = misto_id
            elif rec["naroziste_label"]:
                coords = geocode_nominatim(rec["naroziste_label"])
                nominatim_calls += 1
                if coords:
                    misto_id = upsert_misto(conn, nwid, rec["naroziste_label"],
                                            coords[0], coords[1])
                    if nwid not in place_cache:
                        inserted_mista += 1
                    place_cache[nwid] = misto_id
                else:
                    print(f"[WARN] Could not geocode '{rec['naroziste_label']}' for {rec['jmeno']}")
                    no_place += 1
            else:
                no_place += 1
        else:
            no_place += 1

        upsert_autor(conn, rec, misto_id)
        inserted_autori += 1

    conn.commit()
    conn.close()

    print()
    print("=" * 50)
    print(f"Done.")
    print(f"  Authors inserted/updated : {inserted_autori}")
    print(f"  Places inserted          : {inserted_mista}")
    print(f"  Nominatim calls          : {nominatim_calls}")
    print(f"  Authors without place    : {no_place}")
    print(f"  Skipped (malformed)      : {skipped_parse}")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wikidata → SQLite pipeline for Czech literary map")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite database file")
    args = parser.parse_args()
    run_pipeline(db_path=args.db)
