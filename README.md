# Literární mapa Česka

Interaktivní mapa českých básníků a spisovatelů. Každý pin na mapě představuje místo — rodiště autora. Kliknutím na pin se zobrazí seznam autorů a jejich metadata.

## Spuštění

### Flask server (doporučeno)

Spustí mapu i webové rozhraní pro citace:

```bash
pip install -r requirements.txt
ADMIN_PASSWORD=tajne python server.py
```

Pak otevřete `http://localhost:5000`.

| Adresa | Popis |
|---|---|
| `/` | Interaktivní mapa |
| `/submit` | Veřejný formulář pro přidání citace |
| `/admin` | Moderace citací (vyžaduje heslo) |

### Pouze statická mapa

```bash
python3 -m http.server
# nebo
npx serve .
```

Pak otevřete `http://localhost:8000`.

---

## Datový pipeline

### Požadavky

```bash
pip install -r requirements.txt
```

### 1. Stáhnout data z Wikidata → SQLite

```bash
python data/pipeline.py
```

Stáhne české básníky z Wikidata (SPARQL), normalizuje záznamy a uloží je do `data/literarnimapa.db`.

### 2. Exportovat do JSON pro frontend

```bash
python data/export.py
```

Vygeneruje `public/data.json` ze SQLite databáze.

---

## CLI — správa databáze

```bash
python data/cli.py <příkaz> [volby]
```

### `stats` — celkové statistiky

```bash
python data/cli.py stats
```

### `places` — seznam míst podle počtu autorů

```bash
python data/cli.py places
python data/cli.py places --top 20       # top 20 míst
python data/cli.py places --min 5        # jen místa s 5+ autory
```

### `authors` — seznam autorů

```bash
python data/cli.py authors
python data/cli.py authors --place Praha     # filtrovat podle místa
python data/cli.py authors --place Brno --limit 20
python data/cli.py authors --all             # včetně méně známých autorů
```

### `add-place` — přidat místo ručně

```bash
# Automatické hledání souřadnic přes Nominatim:
python data/cli.py add-place "Telč"

# Nebo zadat souřadnice přímo:
python data/cli.py add-place "Telč" --lat 49.1817 --lon 15.4531

# S Wikidata ID (doporučeno, zabrání duplicitám):
python data/cli.py add-place "Telč" --lat 49.1817 --lon 15.4531 --wikidata-id Q82767
```

### `citations` — seznam citací

```bash
python data/cli.py citations                       # čekající citace (výchozí)
python data/cli.py citations --status approved
python data/cli.py citations --status rejected
python data/cli.py citations --status all
```

### `add-citation` — přidat citaci interaktivně

```bash
python data/cli.py add-citation
```

Průvodce: místo → autor → sbírka → báseň → text → zdroj URL. Citace se uloží se statusem `pending`.

### `approve` / `reject` — moderace citací

```bash
python data/cli.py approve 3    # schválit citaci #3
python data/cli.py reject 3     # zamítnout citaci #3
```

---

## Schéma databáze

```
mista      — místa s GPS souřadnicemi (Wikidata Q-ID)
autori     — autoři navázaní na místo narození
sbirky     — básnické sbírky (navázány na autora)
basne      — básně (navázány na sbírku)
citace     — výňatky navázané na místo (status: pending | approved | rejected)
```

---

## Struktura projektu

```
├── index.html          — frontend (Leaflet mapa)
├── public/data.json    — exportovaná data pro mapu
├── data/
│   ├── pipeline.py     — Wikidata → SQLite
│   ├── export.py       — SQLite → public/data.json
│   ├── cli.py          — správa databáze
│   ├── schema.sql      — definice tabulek
│   └── literarnimapa.db
├── archive/nuxt/       — archivovaná Nuxt verze frontendu
└── requirements.txt
```
