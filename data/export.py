#!/usr/bin/env python3
"""
Export SQLite data to public/data.json for the frontend.

Usage:
    python data/export.py [--db PATH] [--out PATH]
"""

import argparse
import json
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "literarnimapa.db")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "data.json")


def export(db_path: str, out_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    places = conn.execute("SELECT id, nazev, lat, lon FROM mista ORDER BY id").fetchall()

    result = []
    for place in places:
        autori = conn.execute(
            """SELECT jmeno, rok_narozeni, rok_umrti, sitelinks_count, ma_cs_wiki, wikidata_id
               FROM autori
               WHERE naroziste_id = ?
               ORDER BY sitelinks_count DESC""",
            (place["id"],),
        ).fetchall()

        citace = conn.execute(
            """SELECT c.text, c.zdroj_url,
                      COALESCE(b.nazev, '')  AS basen,
                      COALESCE(s.nazev, '')  AS sbirka,
                      COALESCE(a.jmeno, '')  AS autor
               FROM citace c
               LEFT JOIN basne   b ON b.id = c.basen_id
               LEFT JOIN sbirky  s ON s.id = b.sbirka_id
               LEFT JOIN autori  a ON a.id = s.autor_id
               WHERE c.status = 'approved' AND c.misto_id = ?
               ORDER BY c.id""",
            (place["id"],),
        ).fetchall()

        if not autori and not citace:
            continue

        result.append({
            "id":    place["id"],
            "nazev": place["nazev"],
            "lat":   place["lat"],
            "lon":   place["lon"],
            "autori": [
                {
                    "jmeno":          a["jmeno"],
                    "rok_narozeni":   a["rok_narozeni"],
                    "rok_umrti":      a["rok_umrti"],
                    "sitelinks_count":a["sitelinks_count"],
                    "ma_cs_wiki":     bool(a["ma_cs_wiki"]),
                    "wikidata_id":    a["wikidata_id"],
                }
                for a in autori
            ],
            "citace": [
                {
                    "text":     c["text"],
                    "autor":    c["autor"],
                    "sbirka":   c["sbirka"],
                    "basen":    c["basen"],
                    "zdroj_url":c["zdroj_url"],
                }
                for c in citace
            ],
        })

    conn.close()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    total_authors   = sum(len(p["autori"]) for p in result)
    total_citations = sum(len(p["citace"]) for p in result)
    print(f"Exported {len(result)} places, {total_authors} authors, {total_citations} citations → {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export SQLite → public/data.json")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--out", default=OUT_PATH)
    args = parser.parse_args()
    export(db_path=args.db, out_path=args.out)
