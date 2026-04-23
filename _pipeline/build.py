#!/usr/bin/env python3
"""
Build public/data.json by merging two independent data sources:
  1. SQLite (data/literarnimapa.db) — approved user citations + birthplace authors
  2. Corpus XML   (corpus/*.xml)    — curated poetry excerpts with place tags

Merge logic:
  - Group by place
  - SQLite places matched to corpus places by wikidata_id (preferred) or
    normalised place name (fallback)
  - Corpus-only places that have coordinates in places_cache.json become
    new entries
  - Citations deduplicated by (normalised_text) within each place;
    SQLite citations take precedence over identical corpus ones
  - Each corpus citation carries  "source": "corpus"

Usage:
    python build.py [--db PATH] [--corpus DIR] [--cache PATH] [--out PATH]
"""

import argparse
import json
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH    = ROOT / "data" / "literarnimapa.db"
CORPUS_DIR = ROOT / "corpus"
CACHE_PATH = ROOT / "corpus" / "places_cache.json"
OUT_PATH   = ROOT / "public" / "data.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Normalise text for deduplication: lowercase, strip diacritics & spaces."""
    nfkd = unicodedata.normalize("NFKD", text.lower().strip())
    return re.sub(r"\s+", " ", "".join(c for c in nfkd if not unicodedata.combining(c)))


def _place_key(entry: dict) -> str:
    """Stable key for place merging — prefer wikidata_id, fall back to name."""
    wid = entry.get("wikidata_id") or ""
    return wid if wid else _norm(entry.get("nazev", ""))


# ---------------------------------------------------------------------------
# Source 1: SQLite
# ---------------------------------------------------------------------------

def load_sqlite(db_path: Path) -> dict[str, dict]:
    """
    Returns places dict keyed by _place_key.
    Each value: {id, nazev, lat, lon, wikidata_id, autori, citace}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    places_rows = conn.execute(
        "SELECT id, nazev, lat, lon, wikidata_id FROM mista ORDER BY id"
    ).fetchall()

    result: dict[str, dict] = {}

    for p in places_rows:
        autori = conn.execute(
            """SELECT jmeno, rok_narozeni, rok_umrti, sitelinks_count, ma_cs_wiki, wikidata_id
               FROM autori
               WHERE naroziste_id = ?
               ORDER BY sitelinks_count DESC""",
            (p["id"],),
        ).fetchall()

        citace = conn.execute(
            """SELECT c.text, c.zdroj_url,
                      COALESCE(b.nazev, '') AS basen,
                      COALESCE(s.nazev, '') AS sbirka,
                      COALESCE(a.jmeno, '') AS autor
               FROM citace c
               LEFT JOIN basne   b ON b.id = c.basen_id
               LEFT JOIN sbirky  s ON s.id = b.sbirka_id
               LEFT JOIN autori  a ON a.id = s.autor_id
               WHERE c.status = 'approved' AND c.misto_id = ?
               ORDER BY c.id""",
            (p["id"],),
        ).fetchall()

        if not autori and not citace:
            continue

        entry = {
            "id":         p["id"],
            "nazev":      p["nazev"],
            "lat":        p["lat"],
            "lon":        p["lon"],
            "wikidata_id": p["wikidata_id"],
            "autori": [
                {
                    "jmeno":           a["jmeno"],
                    "rok_narozeni":    a["rok_narozeni"],
                    "rok_umrti":       a["rok_umrti"],
                    "sitelinks_count": a["sitelinks_count"],
                    "ma_cs_wiki":      bool(a["ma_cs_wiki"]),
                    "wikidata_id":     a["wikidata_id"],
                }
                for a in autori
            ],
            "citace": [
                {
                    "text":      c["text"],
                    "autor":     c["autor"],
                    "sbirka":    c["sbirka"],
                    "basen":     c["basen"],
                    "zdroj_url": c["zdroj_url"],
                }
                for c in citace
            ],
        }
        result[_place_key(entry)] = entry

    conn.close()
    return result


# ---------------------------------------------------------------------------
# Source 2: Corpus XML
# ---------------------------------------------------------------------------

def _poem_plain_text(poem_elem: ET.Element) -> str:
    """
    Extract display text from a <poem> element: the body after <name>,
    with <place> surface forms preserved (not the XML tags).
    """
    parts: list[str] = []
    name = poem_elem.find("name")

    # Text after </name> tag
    if name is not None and name.tail:
        parts.append(name.tail)
    elif name is None and poem_elem.text:
        parts.append(poem_elem.text)

    for child in poem_elem:
        if child.tag == "name":
            continue
        # <place> → use surface text, then tail
        if child.text:
            parts.append(child.text)
        if child.tail:
            parts.append(child.tail)

    return "".join(parts).strip()


def _poem_lemmas(poem_elem: ET.Element) -> list[str]:
    return [
        p.get("lemma", "").strip()
        for p in poem_elem.findall(".//place")
        if p.get("lemma", "").strip()
    ]


def load_corpus(corpus_dir: Path, cache: dict) -> list[dict]:
    """
    Parse all corpus XML files. Returns a flat list of citation dicts, each
    augmented with place info resolved from places_cache.

    Format per item:
      {nazev, lat, lon, wikidata_id, citace_entry}
    where citace_entry matches the SQLite citace schema plus "source".
    """
    xml_files = sorted(corpus_dir.glob("*.xml"))
    items: list[dict] = []
    skipped_lemmas: set[str] = set()

    for xml_file in xml_files:
        raw = xml_file.read_text(encoding="utf-8")
        try:
            root = ET.fromstring(f"<corpus>{raw}</corpus>")
        except ET.ParseError as exc:
            print(f"  Warning: XML parse error in {xml_file.name}: {exc}")
            continue

        collection_title = root.findtext("title", "").strip()
        author           = root.findtext("author", "").strip()
        volne_dilo_text  = root.findtext("volne_dilo", "false").strip().lower()

        if volne_dilo_text != "true":
            print(f"  Skipping {xml_file.name}: volne_dilo is not 'true'")
            continue

        for poem in root.findall("poem"):
            poem_name   = (poem.findtext("name") or "").strip()
            poem_text   = _poem_plain_text(poem)
            place_lemmas = _poem_lemmas(poem)

            if not poem_text or not place_lemmas:
                continue

            for lemma in place_lemmas:
                place_info = cache.get(lemma)
                if not place_info:
                    skipped_lemmas.add(lemma)
                    continue
                if place_info.get("lat") is None or place_info.get("lon") is None:
                    skipped_lemmas.add(lemma)
                    continue

                items.append({
                    "nazev":      place_info.get("nazev") or lemma,
                    "lat":        place_info["lat"],
                    "lon":        place_info["lon"],
                    "wikidata_id": place_info.get("wikidata_id"),
                    "citace": {
                        "text":      poem_text,
                        "autor":     author,
                        "sbirka":    collection_title,
                        "basen":     poem_name,
                        "zdroj_url": None,
                        "source":    "corpus",
                    },
                })

    if skipped_lemmas:
        print(
            f"  Skipped {len(skipped_lemmas)} lemma(s) with no cache entry "
            f"(run geocode_places.py): {', '.join(sorted(skipped_lemmas))}"
        )

    return items


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge(sqlite_places: dict[str, dict], corpus_items: list[dict]) -> list[dict]:
    """
    Merge corpus citations into the sqlite_places dict, creating new place
    entries where needed. Returns final list sorted by place id.
    """
    next_id = max((p["id"] for p in sqlite_places.values()), default=0) + 1

    # Track seen citation texts per place to avoid duplicates
    seen_texts: dict[str, set[str]] = {
        key: {_norm(c["text"]) for c in place["citace"]}
        for key, place in sqlite_places.items()
    }

    for item in corpus_items:
        place_entry: dict = {
            "wikidata_id": item["wikidata_id"],
            "nazev":       item["nazev"],
        }
        key = _place_key(place_entry)
        norm_text = _norm(item["citace"]["text"])

        if key in sqlite_places:
            # Add citation to existing place (if not duplicate)
            if norm_text not in seen_texts[key]:
                sqlite_places[key]["citace"].append(item["citace"])
                seen_texts[key].add(norm_text)
        else:
            # New place from corpus
            sqlite_places[key] = {
                "id":         next_id,
                "nazev":      item["nazev"],
                "lat":        item["lat"],
                "lon":        item["lon"],
                "wikidata_id": item["wikidata_id"],
                "autori":     [],
                "citace":     [item["citace"]],
            }
            seen_texts[key] = {norm_text}
            next_id += 1

    # Sort by id; strip internal wikidata_id key before output
    out = sorted(sqlite_places.values(), key=lambda p: p["id"])
    for p in out:
        p.pop("wikidata_id", None)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build(db_path: Path, corpus_dir: Path, cache_path: Path, out_path: Path) -> None:
    print(f"Loading SQLite: {db_path}")
    sqlite_places = load_sqlite(db_path)
    print(f"  {len(sqlite_places)} places with authors/citations")

    cache: dict = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    print(f"Loading places cache: {len(cache)} entries")

    if corpus_dir.is_dir():
        xml_count = len(list(corpus_dir.glob("*.xml")))
        print(f"Loading corpus: {xml_count} XML file(s) in {corpus_dir}")
        corpus_items = load_corpus(corpus_dir, cache)
        print(f"  {len(corpus_items)} citation-place pairs from corpus")
    else:
        print(f"Corpus dir not found ({corpus_dir}) — skipping corpus sources")
        corpus_items = []

    result = merge(sqlite_places, corpus_items)

    total_authors   = sum(len(p["autori"])  for p in result)
    total_citations = sum(len(p["citace"])  for p in result)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(
        f"Exported: {len(result)} places, {total_authors} authors, "
        f"{total_citations} citations → {out_path}"
    )


def main():
    parser = argparse.ArgumentParser(description="Build public/data.json from SQLite + corpus")
    parser.add_argument("--db",     default=str(DB_PATH),    help=f"SQLite DB (default: {DB_PATH})")
    parser.add_argument("--corpus", default=str(CORPUS_DIR), help=f"Corpus dir (default: {CORPUS_DIR})")
    parser.add_argument("--cache",  default=str(CACHE_PATH), help=f"places_cache.json (default: {CACHE_PATH})")
    parser.add_argument("--out",    default=str(OUT_PATH),   help=f"Output JSON (default: {OUT_PATH})")
    args = parser.parse_args()

    build(
        db_path    = Path(args.db),
        corpus_dir = Path(args.corpus),
        cache_path = Path(args.cache),
        out_path   = Path(args.out),
    )


if __name__ == "__main__":
    main()
