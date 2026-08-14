# Allocura Matching

[Englische Version](README.md)

Allocura Matching ist ein nachvollziehbares Entscheidungsunterstützungssystem, das normalisierte
Anfragepositionen für Medikamente und medizinische Ausrüstung passenden Katalogvarianten zuordnet.
Es liefert eine kurze, prüfbare Kandidatenliste, die ein Mensch bestätigt. Das System trifft keine
eigenständigen klinischen oder beschaffungsbezogenen Entscheidungen.

## Was dieses Paket leistet

Für jede normalisierte Anfrageposition führt der Dienst folgende Schritte aus:

1. Er validiert den versionierten Eingabevertrag.
2. Er erstellt deterministische semantische und kanonische Textrepräsentationen.
3. Er ermittelt Kandidaten über exakte, lexikalische, vektorbasierte und historische Suchkanäle.
4. Er führt diese Listen mittels Reciprocal Rank Fusion zusammen.
5. Er prüft versionierte Regeln für Medikamente und medizinische Ausrüstung.
6. Er berechnet nachvollziehbare Verpackungsoptionen und konservative Bestandsinformationen.
7. Er ordnet geeignete Kandidaten deterministisch.
8. Er liefert bis zu zehn Kandidaten mit Begründungen, Warnungen und Herkunftsnachweisen.
9. Er speichert den vollständigen Matching-Lauf und die spätere menschliche Entscheidung.

Dieselben Eingaben sowie dieselben Quellen-, Algorithmus-, Regelwerk- und Embedding-Modellversionen
erzeugen dieselbe Reihenfolge.

## Was dieses Paket nicht leistet

- Es liest keine Excel-, PDF-, E-Mail-, Outlook- oder SharePoint-Dateien ein.
- Es leitet keine fehlenden Wirkstärken, Größen, Haltbarkeiten oder Ersatzprodukte ab.
- Es berechnet keinen verfügbaren Angebotsbestand, solange action medeor die Formel nicht bestätigt.
- Es behandelt einen Embedding-Score nicht als Wahrscheinlichkeit für die Richtigkeit.
- Es lernt nicht unmittelbar aus jedem Klick.
- Es verändert den Figma-UI-Branch nicht und hängt nicht von ihm ab.

Extraktionssysteme müssen Daten gemäß `InquiryLineV1`, `InventoryItemV1` und `HistoricalOfferV1`
bereitstellen. Die ursprünglichen Quellwerte und Herkunftsnachweise bleiben mit jedem normalisierten
Datensatz verbunden.

## Paketstruktur

```text
matching/
├── contracts.py       Versionierte API- und Quelldatenverträge
├── domain.py          Interner Kandidatenzustand
├── ports.py           Schnittstellen für Katalog, Vektoren, Historie, Modelle und Läufe
├── representation.py Deterministische durchsuchbare Texte
├── validation.py      Defensive Eingabevalidierung
├── retrieval/         Exakte, lexikalische, vektorbasierte und historische Suche sowie Fusion
├── constraints/       Regelbasierte Prüfungen für Medikamente und Ausrüstung
├── packaging.py       Verpackungsoptionen und Bestandsnachweise
├── ranking/           Nachvollziehbare Merkmale und deterministische Reihenfolge
├── adapters/          In-Memory- und PostgreSQL-/pgvector-Implementierungen
├── service.py         Steuerung des Matching-Ablaufs
├── api.py             Von der UI unabhängige HTTP-Schnittstelle
└── README_DETAILED_DE.md Architektur, Begründungen, Sicherheit und Roadmap
```

## HTTP-API

```text
POST /api/v1/match-runs
GET  /api/v1/match-runs/{match_run_id}
POST /api/v1/match-decisions
```

Die API akzeptiert normalisiertes JSON und keine hochgeladenen Quelldateien. Die Figma-UI kann später
über einen schlanken Mapper an diese API angebunden werden, ohne die Matching-Domäne an React-Typen
zu koppeln.

## Lokale Entwicklung

Im Verzeichnis `apps/backend`:

```bash
uv sync
uv run pytest -q
uv run ruff check .
```

Die Datenbank mit pgvector starten und anschließend die Migrationen anwenden:

```bash
docker compose up -d db
uv run alembic upgrade head
```

Die Standardmigration erstellt versionierte Tabellen für Katalog, Bestand, Embeddings, Historie,
Matching-Läufe, Kandidaten, Entscheidungen und ausdrücklich freigegebene Partnerpräferenzen.

## Aktueller Stand des Algorithmus

Bereits umgesetzt:

- exakte und deterministische lexikalische Suche;
- Vektorsuche über eine modellunabhängige pgvector-Schnittstelle;
- historische Suche als nicht maßgebliches Signal zur Verbesserung der Trefferabdeckung;
- Zusammenführung der Ranglisten mittels Reciprocal Rank Fusion;
- konservative, regelbasierte Einschränkungen;
- nachvollziehbare Verpackungsberechnungen;
- deterministische Top-K-Rangfolge;
- unveränderliche Matching-Läufe und Entscheidungen;
- Rückfallmechanismen, wenn Vektor- oder Verlaufsdaten fehlen.

Noch nicht ausgewählt oder freigegeben:

- ein produktives mehrsprachiges Embedding-Modell;
- bestätigte Verfügbarkeits- und Substitutionsregeln von action medeor;
- eine erlernte Rangfolge oder kalibrierte Konfidenz;
- Live-Anbindungen an ERP, SharePoint, Outlook oder Lieferanten.

Vor Änderungen am Matching-Verhalten bitte
[README_DETAILED_DE.md](README_DETAILED_DE.md) lesen.
