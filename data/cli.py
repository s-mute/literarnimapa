#!/usr/bin/env python3
"""
CLI for inspecting and managing the Literární mapa database.

Usage:
    python data/cli.py <command> [options]

Commands:
    stats                       Overall counts
    places  [--min N] [--top N] Places sorted by author count
    authors [--place NAZEV]     Authors, optionally filtered by place
              [--limit N]
              [--all]           Include less-known (sitelinks < 3, no cs.wiki)
    citations [--status S]      List citations (pending/approved/rejected/all)
    add-citation                Add a citation interactively
    approve  <id>               Approve a pending citation
    reject   <id>               Reject a pending citation
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pipeline import geocode_nominatim

DB_PATH = os.path.join(os.path.dirname(__file__), "literarnimapa.db")


def get_conn(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        sys.exit(f"[ERROR] Database not found: {db_path}\n"
                 f"        Run: python data/pipeline.py")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Formatting helpers ────────────────────────────────────────────────────────

def hr(char="─", width=60):
    print(char * width)

def col(value, width, align="<"):
    s = str(value) if value is not None else "—"
    return f"{s:{align}{width}}"


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_stats(conn: sqlite3.Connection, _args) -> None:
    row = conn.execute("""
        SELECT
          (SELECT COUNT(*) FROM mista)   AS mista,
          (SELECT COUNT(*) FROM autori)  AS autori,
          (SELECT COUNT(*) FROM sbirky)  AS sbirky,
          (SELECT COUNT(*) FROM basne)   AS basne,
          (SELECT COUNT(*) FROM citace)  AS citace,
          (SELECT COUNT(*) FROM citace WHERE status = 'pending')  AS pending,
          (SELECT COUNT(*) FROM citace WHERE status = 'approved') AS approved,
          (SELECT COUNT(*) FROM citace WHERE status = 'rejected') AS rejected
    """).fetchone()

    print()
    print("  Literární mapa Česka — databáze")
    hr()
    print(f"  Místa (mista)       {row['mista']:>6}")
    print(f"  Autoři (autori)     {row['autori']:>6}")
    print(f"  Sbírky (sbirky)     {row['sbirky']:>6}")
    print(f"  Básně  (basne)      {row['basne']:>6}")
    print(f"  Citace (citace)     {row['citace']:>6}")
    if row["citace"]:
        print(f"    → pending         {row['pending']:>6}")
        print(f"    → approved        {row['approved']:>6}")
        print(f"    → rejected        {row['rejected']:>6}")
    hr()
    print()


def cmd_places(conn: sqlite3.Connection, args) -> None:
    min_authors = args.min
    top = args.top

    rows = conn.execute("""
        SELECT m.id, m.nazev, m.lat, m.lon,
               COUNT(a.id) AS pocet_autoru
        FROM mista m
        LEFT JOIN autori a ON a.naroziste_id = m.id
        GROUP BY m.id
        HAVING pocet_autoru >= ?
        ORDER BY pocet_autoru DESC, m.nazev
        LIMIT ?
    """, (min_authors, top)).fetchall()

    print()
    print(f"  {'ID':<6} {'Místo':<30} {'Autoři':>6}  {'Souřadnice'}")
    hr()
    for r in rows:
        coords = f"{r['lat']:.4f}, {r['lon']:.4f}"
        print(f"  {col(r['id'], 6)} {col(r['nazev'], 30)} {r['pocet_autoru']:>6}  {coords}")
    hr()
    print(f"  {len(rows)} míst\n")


def cmd_authors(conn: sqlite3.Connection, args) -> None:
    params: list = []
    where_clauses = ["1=1"]

    if args.place:
        where_clauses.append("LOWER(m.nazev) LIKE LOWER(?)")
        params.append(f"%{args.place}%")

    if not args.all:
        where_clauses.append("(a.sitelinks_count >= 3 OR a.ma_cs_wiki = 1)")

    where = " AND ".join(where_clauses)
    params.append(args.limit)

    rows = conn.execute(f"""
        SELECT a.id, a.jmeno, a.rok_narozeni, a.rok_umrti,
               a.sitelinks_count, a.ma_cs_wiki, a.wikidata_id,
               m.nazev AS misto
        FROM autori a
        LEFT JOIN mista m ON m.id = a.naroziste_id
        WHERE {where}
        ORDER BY a.sitelinks_count DESC, a.jmeno
        LIMIT ?
    """, params).fetchall()

    print()
    print(f"  {'ID':<6} {'Jméno':<30} {'Roky':<12} {'Sitelinks':>9}  {'cs?':<4} {'Místo'}")
    hr(width=80)
    for r in rows:
        years = f"{r['rok_narozeni'] or '?'}–{r['rok_umrti'] or ''}"
        cs = "✓" if r["ma_cs_wiki"] else ""
        misto = r["misto"] or "—"
        print(f"  {col(r['id'], 6)} {col(r['jmeno'], 30)} {col(years, 12)} "
              f"{r['sitelinks_count']:>9}  {col(cs, 4)} {misto}")
    hr(width=80)
    print(f"  {len(rows)} autorů\n")


def cmd_citations(conn: sqlite3.Connection, args) -> None:
    status = args.status
    params: list = []
    where = "1=1"
    if status != "all":
        where = "c.status = ?"
        params.append(status)

    rows = conn.execute(f"""
        SELECT c.id, c.status, c.text, c.pridano,
               m.nazev AS misto,
               b.nazev AS basen,
               s.nazev AS sbirka,
               a.jmeno AS autor
        FROM citace c
        LEFT JOIN mista m ON m.id = c.misto_id
        LEFT JOIN basne b ON b.id = c.basen_id
        LEFT JOIN sbirky s ON s.id = b.sbirka_id
        LEFT JOIN autori a ON a.id = s.autor_id
        WHERE {where}
        ORDER BY c.pridano DESC
    """, params).fetchall()

    if not rows:
        print(f"\n  Žádné citace (status={status})\n")
        return

    print()
    for r in rows:
        status_tag = {"pending": "[ČEKÁ]", "approved": "[OK]   ", "rejected": "[ZAMÍT]"}.get(r["status"], r["status"])
        print(f"  #{r['id']} {status_tag}  {r['misto'] or '—'}  |  {r['autor'] or '—'}: {r['basen'] or r['sbirka'] or '—'}")
        for line in r["text"].split("\n"):
            print(f"      {line}")
        print(f"      přidáno: {r['pridano']}")
        hr(width=60)
    print(f"  {len(rows)} citací\n")


def cmd_add_citation(conn: sqlite3.Connection, _args) -> None:
    print("\n  Přidat citaci")
    hr()

    # Pick place
    place_q = input("  Místo (část názvu): ").strip()
    places = conn.execute(
        "SELECT id, nazev FROM mista WHERE LOWER(nazev) LIKE LOWER(?) ORDER BY nazev LIMIT 10",
        (f"%{place_q}%",)
    ).fetchall()
    if not places:
        print("  Místo nenalezeno.")
        return
    for i, p in enumerate(places):
        print(f"    {i+1}. {p['nazev']} (id={p['id']})")
    idx = int(input("  Vyberte číslo: ").strip()) - 1
    misto_id = places[idx]["id"]

    # Pick or create author → collection → poem
    autor_q = input("  Autor (část jména): ").strip()
    autori = conn.execute(
        "SELECT id, jmeno FROM autori WHERE LOWER(jmeno) LIKE LOWER(?) ORDER BY sitelinks_count DESC LIMIT 10",
        (f"%{autor_q}%",)
    ).fetchall()
    if not autori:
        print("  Autor nenalezen.")
        return
    for i, a in enumerate(autori):
        print(f"    {i+1}. {a['jmeno']} (id={a['id']})")
    idx = int(input("  Vyberte číslo: ").strip()) - 1
    autor_id = autori[idx]["id"]

    nazev_sbirky = input("  Název sbírky: ").strip()
    rok_vydani_raw = input("  Rok vydání sbírky (Enter = přeskočit): ").strip()
    rok_vydani = int(rok_vydani_raw) if rok_vydani_raw else None

    conn.execute(
        "INSERT INTO sbirky (autor_id, nazev, rok_vydani) VALUES (?, ?, ?)",
        (autor_id, nazev_sbirky, rok_vydani)
    )
    sbirka_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    nazev_basne = input("  Název básně (Enter = přeskočit): ").strip() or None
    conn.execute("INSERT INTO basne (sbirka_id, nazev) VALUES (?, ?)", (sbirka_id, nazev_basne))
    basen_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    print("  Text citace (prázdný řádek = konec):")
    lines = []
    while True:
        line = input("    ")
        if not line:
            break
        lines.append(line)
    text = "\n".join(lines)

    zdroj = input("  Zdroj URL (Enter = přeskočit): ").strip() or None

    conn.execute(
        "INSERT INTO citace (basen_id, misto_id, text, status, zdroj_url) VALUES (?, ?, ?, 'pending', ?)",
        (basen_id, misto_id, text, zdroj)
    )
    conn.commit()
    print("\n  ✓ Citace přidána (status: pending)\n")


def cmd_add_place(conn: sqlite3.Connection, args) -> None:
    print("\n  Přidat místo")
    hr()

    nazev = (args.nazev or input("  Název místa: ").strip())
    if not nazev:
        sys.exit("  [ERROR] Název nesmí být prázdný.")

    # Try Nominatim if no coords given
    lat, lon = args.lat, args.lon
    if lat is None or lon is None:
        print(f"  Hledám souřadnice pro '{nazev}' přes Nominatim...")
        coords = geocode_nominatim(nazev)
        if coords:
            lat, lon = coords
            print(f"  Nalezeno: {lat:.5f}, {lon:.5f}")
        else:
            lat = float(input("  Zeměpisná šířka (lat): ").strip())
            lon = float(input("  Zeměpisná délka (lon): ").strip())

    wikidata_id = args.wikidata_id or input("  Wikidata ID (např. Q1085, Enter = přeskočit): ").strip() or None

    try:
        conn.execute(
            "INSERT INTO mista (nazev, lat, lon, wikidata_id) VALUES (?, ?, ?, ?)",
            (nazev, lat, lon, wikidata_id),
        )
        conn.commit()
        row = conn.execute("SELECT last_insert_rowid()").fetchone()
        print(f"\n  ✓ Místo přidáno (id={row[0]}): {nazev} [{lat:.5f}, {lon:.5f}]\n")
    except sqlite3.IntegrityError:
        sys.exit(f"  [ERROR] Místo s Wikidata ID '{wikidata_id}' již existuje.")


def cmd_approve(conn: sqlite3.Connection, args) -> None:
    cur = conn.execute("UPDATE citace SET status = 'approved' WHERE id = ?", (args.id,))
    conn.commit()
    if cur.rowcount:
        print(f"  ✓ Citace #{args.id} schválena")
    else:
        print(f"  Citace #{args.id} nenalezena")


def cmd_reject(conn: sqlite3.Connection, args) -> None:
    cur = conn.execute("UPDATE citace SET status = 'rejected' WHERE id = ?", (args.id,))
    conn.commit()
    if cur.rowcount:
        print(f"  ✓ Citace #{args.id} zamítnuta")
    else:
        print(f"  Citace #{args.id} nenalezena")


# ── Argument parser ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python data/cli.py",
        description="Literární mapa Česka — správa databáze",
    )
    parser.add_argument("--db", default=DB_PATH, help="Cesta k SQLite databázi")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Celkové statistiky")

    p_places = sub.add_parser("places", help="Seznam míst podle počtu autorů")
    p_places.add_argument("--min", type=int, default=1, metavar="N", help="Minimální počet autorů (výchozí: 1)")
    p_places.add_argument("--top", type=int, default=50, metavar="N", help="Počet výsledků (výchozí: 50)")

    p_authors = sub.add_parser("authors", help="Seznam autorů")
    p_authors.add_argument("--place", metavar="NAZEV", help="Filtrovat podle místa")
    p_authors.add_argument("--limit", type=int, default=50, metavar="N")
    p_authors.add_argument("--all", action="store_true", help="Zahrnout i méně známé autory")

    p_cit = sub.add_parser("citations", help="Seznam citací")
    p_cit.add_argument("--status", default="pending",
                       choices=["pending", "approved", "rejected", "all"])

    p_add_place = sub.add_parser("add-place", help="Přidat místo ručně")
    p_add_place.add_argument("nazev", nargs="?", help="Název místa")
    p_add_place.add_argument("--lat", type=float, help="Zeměpisná šířka")
    p_add_place.add_argument("--lon", type=float, help="Zeměpisná délka")
    p_add_place.add_argument("--wikidata-id", dest="wikidata_id", metavar="QID")

    sub.add_parser("add-citation", help="Přidat citaci interaktivně")

    p_approve = sub.add_parser("approve", help="Schválit citaci")
    p_approve.add_argument("id", type=int)

    p_reject = sub.add_parser("reject", help="Zamítnout citaci")
    p_reject.add_argument("id", type=int)

    args = parser.parse_args()
    conn = get_conn(args.db)

    commands = {
        "stats":        cmd_stats,
        "places":       cmd_places,
        "authors":      cmd_authors,
        "citations":    cmd_citations,
        "add-place":    cmd_add_place,
        "add-citation": cmd_add_citation,
        "approve":      cmd_approve,
        "reject":       cmd_reject,
    }
    commands[args.command](conn, args)
    conn.close()


if __name__ == "__main__":
    main()
