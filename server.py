#!/usr/bin/env python3
"""
Flask server for Literární mapa Česka.

Run:
    python server.py
"""
import os
import sqlite3

from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "literarnimapa.db")

app = Flask(__name__, static_folder="public", static_url_path="/public")


# ── Database ───────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


# ── Static ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


# ── Read-only API ──────────────────────────────────────────────────────────────

@app.route("/api/places")
def api_places():
    q = request.args.get("q", "").strip()
    rows = get_db().execute(
        "SELECT id, nazev FROM mista WHERE LOWER(nazev) LIKE LOWER(?) ORDER BY nazev LIMIT 15",
        (f"%{q}%",),
    ).fetchall()
    return jsonify([{"id": r["id"], "nazev": r["nazev"]} for r in rows])


@app.route("/api/authors")
def api_authors():
    q = request.args.get("q", "").strip()
    rows = get_db().execute(
        """SELECT id, jmeno, rok_narozeni, rok_umrti
           FROM autori
           WHERE LOWER(jmeno) LIKE LOWER(?)
           ORDER BY sitelinks_count DESC, jmeno
           LIMIT 15""",
        (f"%{q}%",),
    ).fetchall()
    return jsonify([
        {
            "id": r["id"],
            "jmeno": r["jmeno"],
            "roky": f"{r['rok_narozeni'] or '?'}–{r['rok_umrti'] or ''}",
        }
        for r in rows
    ])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
