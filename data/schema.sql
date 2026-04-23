CREATE TABLE IF NOT EXISTS mista (
  id          INTEGER PRIMARY KEY,
  nazev       TEXT NOT NULL,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  wikidata_id TEXT UNIQUE  -- Q-identifier, e.g. "Q1085"
);

CREATE TABLE IF NOT EXISTS autori (
  id              INTEGER PRIMARY KEY,
  jmeno           TEXT NOT NULL,
  rok_narozeni    INTEGER,
  rok_umrti       INTEGER,
  naroziste_id    INTEGER REFERENCES mista(id),
  wikidata_id     TEXT UNIQUE,
  sitelinks_count INTEGER DEFAULT 0,
  ma_cs_wiki      BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS sbirky (
  id         INTEGER PRIMARY KEY,
  autor_id   INTEGER REFERENCES autori(id),
  nazev      TEXT NOT NULL,
  rok_vydani INTEGER,
  nakladatel TEXT,
  volne_dilo BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS basne (
  id        INTEGER PRIMARY KEY,
  sbirka_id INTEGER REFERENCES sbirky(id),
  nazev     TEXT
);

CREATE TABLE IF NOT EXISTS citace (
  id        INTEGER PRIMARY KEY,
  basen_id  INTEGER REFERENCES basne(id),
  misto_id  INTEGER REFERENCES mista(id),
  text      TEXT NOT NULL,
  status    TEXT DEFAULT 'pending',  -- pending | approved | rejected
  zdroj_url TEXT,
  pridano   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
