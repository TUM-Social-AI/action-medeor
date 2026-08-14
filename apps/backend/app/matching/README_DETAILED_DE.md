# Allocura Matching: Architektur und Begründung

[Englische Version](README_DETAILED.md)

## 1. Zweck

Allocura unterstützt die Mitarbeitenden von action medeor dabei, mehrsprachige Anfragen nach
Medikamenten und medizinischer Ausrüstung freigegebenen Katalogvarianten und bei Bedarf historischen
Beschaffungsnachweisen zuzuordnen. Die Software ist ein Entscheidungsunterstützungssystem: Sie schlägt
Kandidaten vor, erklärt diese und zeichnet die menschliche Entscheidung auf. Sie darf weder
stillschweigend eine klinische Gleichwertigkeit behaupten noch unsichere Daten als bestätigte
Tatsachen darstellen.

Das Framework ist auf Zuverlässigkeit, Testbarkeit, Prüfbarkeit, Modularität und schrittweise
Skalierbarkeit ausgelegt. Es beginnt bewusst mit einem konservativen, deterministischen Verhalten und
hält probabilistische Komponenten austauschbar.

## 2. Unverhandelbare Grundsätze

1. **Rohwerte sind unveränderliche Nachweise.** Normalisierte oder abgeleitete Werte überschreiben
   niemals die Quelldaten.
2. **Unbekannt bedeutet weder falsch noch null.** Ein fehlender Preis bedeutet nicht kostenlos; eine
   fehlende Haltbarkeit bedeutet nicht ausreichend.
3. **Die Suche ist keine Freigabe.** Embeddings und Verlaufsdaten erzeugen Kandidaten, aber niemals
   klinische Regeln.
4. **Harte Regeln konkurrieren nicht mit dem Preis.** Ein bestätigter Ausschluss kann nicht durch ein
   günstiges, verfügbares Produkt aufgewogen werden.
5. **Jedes Ergebnis ist reproduzierbar.** Algorithmus-, Regelwerk-, Modell- und Datenversionen werden
   aufgezeichnet.
6. **Ein gültiges Ergebnis darf keinen Kandidaten enthalten.** Der Dienst füllt die Top 10 niemals mit
   unsicheren Optionen auf.
7. **Menschliche Entscheidungen sind separate Ereignisse.** Eine Empfehlung ist keine Bestätigung.

## 3. Systemgrenze

Das Matching beginnt nach der Extraktion.

```text
Excel / Outlook / PDF / SharePoint / ERP
                    │
            quellenspezifische Extraktion
                    │
       versionierte normalisierte Verträge
                    │
             Matching-Framework
```

Das Matching-Paket verarbeitet niemals Arbeitsmappen, E-Mail-Texte, PDF-Layouts, Zellfarben oder
SharePoint-Ordner. Diese Aufgaben gehören in die Eingangs- und Extraktionsadapter. Diese Grenze
verhindert, dass Änderungen an Quellformaten das sicherheitsrelevante Matching-Verhalten
beeinträchtigen.

### Outlook-Grenze

Ein Outlook-Connector sollte künftig ein eigenes Postfach oder einen eigenen Ordner, unveränderliche
Microsoft-Graph-Nachrichten-IDs, Änderungsbenachrichtigungen mit Delta-Abgleich sowie eine
unveränderliche MIME- und Anhangsspeicherung verwenden. Sein Extraktor muss dieselben normalisierten
Verträge wie die Excel-Extraktion ausgeben. Das Matching speichert lediglich eine generische
`SourceReferenceV1`, sodass eine aus Outlook stammende Position dieselbe Pipeline durchläuft.

## 4. Versionierte Verträge

### `InquiryLineV1`

Enthält die ursprüngliche Beschreibung, eine optionale Übersetzung, die normalisierte Mengen- und
Verpackungsanforderung, strukturierte Attribute, Partner- und Zielkontext, Extraktionswarnungen sowie
eine präzise Quellenreferenz.

### `InventoryItemV1`

Enthält eine Artikelnummer als Zeichenkette, den Produktbereich, Beschreibungen, normalisierte
Attribute, Hersteller, Marke, Verpackung, Nachbeschaffungs- und T1-Werte, maßgebliche Aktivitäts- und
Qualitätskennzeichen, Bestandsrohwerte sowie die Quellversion.

### `HistoricalOfferV1`

Enthält den historischen Anfragetext, den zugeordneten Artikel, sofern bekannt, Lieferantennachweise,
Preisbasis, Verpackung, Datum, Kontext sowie SharePoint- beziehungsweise Quellenherkunft.

### Warum die Verträge strikt sind

Alle öffentlichen Modelle lehnen unerwartete Felder ab. Dadurch werden Abweichungen früh erkannt: Ein
Extraktionsteam kann nicht unbemerkt `quantity.unit` umbenennen, eine Artikelnummer in eine
Fließkommazahl umwandeln oder unbekannte Sterilität zu `false` zusammenfassen. Die Vertragsversion `1`
ermöglicht eine spätere V2, ohne die historische Reproduzierbarkeit zu beeinträchtigen.

## 5. Validierung

Pydantic prüft Struktur und Typen. `validation.py` ergänzt matching-spezifische Diagnosen, zum
Beispiel:

- normalisierte Menge fehlt;
- Mengeneinheit fehlt;
- keine strukturierten Attribute übergeben;
- Warnungen aus der vorgelagerten Extraktion.

Die Validierung liefert `valid`, `valid_with_warnings`, `review_required` oder `invalid`. Fehlende
Verpackungsdaten verhindern die Textsuche nicht; das Ergebnis weist jedoch ausdrücklich darauf hin,
dass die Verpackung nicht berechnet werden kann.

## 6. Suchrepräsentation

Das Framework erzeugt zwei deterministische Zeichenketten.

```text
semantischer Kern:
  urinary Foley catheter sterile balloon

kanonischer Text:
  urinary Foley catheter sterile balloon; charriere=18 ch; single_use=true
```

Der semantische Kern unterstützt die mehrsprachige Bedeutung. Die kanonische Form bildet zusätzlich
normalisierte Attribute ab, sodass Embedding-Inhalte versionierbar und prüfbar werden. Zahlen werden
nicht pauschal entfernt: Sie verbessern die Trefferabdeckung, während strukturierte Regeln maßgeblich
bleiben.

Unicode wird mit NFKC normalisiert und die Tokens werden deterministisch erzeugt. Ein SHA-256-Inhalts-
Hash kennzeichnet exakt, welche Repräsentation eingebettet wurde.

## 7. Suchkanäle

### Exakte Suche

Findet eine ausdrücklich angefragte Artikelnummer oder eine identische normalisierte Beschreibung.
Sie liefert ein starkes Signal, durchläuft aber weiterhin die Aktivitäts-, Qualitäts- und sonstigen
Regeln.

### Lexikalische Suche

Verwendet einen von zusätzlichen Abhängigkeiten freien Zeichenähnlichkeitsvergleich und
Tokenüberschneidungen. Damit werden Schreibvarianten, Teilüberschneidungen, Codes und technische Namen
erfasst. Sie ist die transparente Basis und bleibt verfügbar, wenn maschinelles Lernen deaktiviert
ist.

### Vektorsuche

Verwendet die Kosinusdistanz in PostgreSQL/pgvector. Vektoren werden nur verglichen, wenn die
registrierte Modell-ID und die Dimensionen übereinstimmen. Die Datenbank speichert Vektoren mit
variabler Dimension, sodass spätere Modellexperimente keine Neugestaltung des Schemas erfordern. Ein
modellspezifischer approximativer Index kann später ergänzt werden.

Das Framework enthält bewusst noch kein produktives Embedding-Modell. `EmbeddingProvider` ist eine
Schnittstelle, und die Tests verwenden einen deterministischen Testanbieter. Ein echtes Modell muss
einen mehrsprachigen, domänenspezifischen Benchmark gewinnen und die Prüfung von Lizenz, Kosten,
Aufbewahrung und Datenresidenz bestehen.

### Historische Suche

Findet frühere Anfragetexte, die Katalogartikeln zugeordnet sind. Partner- und Zielkontext grenzen die
Suche ein. Die Historie kann einen Artikel in den Kandidatenpool aufnehmen und einen prüfbaren Score
beisteuern; sie darf weder aktuelle Regeln umgehen noch eine falsche Garantie als „historisch
verifiziert“ erhalten.

### Warum die Pipeline nicht einfach „erst filtern, dann bewerten“ verwendet

Die Pipeline filtert selektiv. Der vertrauenswürdige Produktbereich wird vor der Suche angewendet,
weil ein Medikament und ein Ausrüstungsgegenstand nicht austauschbar sind. Detaillierte Attribute
werden nicht als Datenbankfilter verwendet: Extrahierte Werte können unvollständig oder unterschiedlich
normalisiert sein, und ein früher Filter würde unbemerkt die Trefferabdeckung verschlechtern.
Stattdessen erzeugen exakte, lexikalische, vektorbasierte und historische Suche eine breite, aber
begrenzte Vereinigungsmenge. Maßgebliche Sicherheits- und Statusregeln entfernen anschließend
unzulässige Kandidaten, Prüfregeln kennzeichnen Unsicherheit und eine deterministische Rangfolge ordnet
die verbleibenden Kandidaten. Bei der aktuellen Kataloggröße ist dieses Verfahren schnell und leichter
prüfbar als eine vorschnell eingeführte Graph- oder approximative Suchschicht. Weitere nachweislich
sichere Vorfilter können mit einer neuen Regelversion ergänzt werden, sobald Skalierung oder gemessene
Latenz dies erfordern.

## 8. Kandidatenfusion

Die Scores der Suchverfahren haben unterschiedliche Bedeutungen und Wertebereiche. Kosinusähnlichkeit,
Textähnlichkeit, ein Exaktheitskennzeichen und historische Häufigkeit dürfen nicht direkt addiert
werden.

Die erste Implementierung verwendet Reciprocal Rank Fusion (RRF):

```text
RRF(Artikel) = Summe(1 / (k + Rang_im_Suchverfahren))
```

RRF bevorzugt Kandidaten, die von mehreren unabhängigen Kanälen weit oben gefunden wurden,
dedupliziert Artikelnummern und gibt nicht vor, dass heterogene Scores kalibriert seien. Die einzelnen
Nachweise bleiben am Kandidaten erhalten.

## 9. Regelwerk

Die Engine wird durch ein versioniertes Regelwerk gesteuert. Eine Regel liefert:

- `pass`: bestanden;
- `exclude`: ausschließen;
- `review`: manuell prüfen;
- `warning`: Warnung;
- `unknown`: unbekannt.

Jedes Ergebnis enthält einen stabilen Begründungscode, eine verständliche Erklärung, die verglichenen
Werte, den Attributnamen und die Regelwerkversion.

### Sicheres V1-Verhalten

Nur ein maßgeblicher Katalogstatus führt derzeit automatisch zu einem harten Ausschluss:

- falscher Produktbereich;
- Artikel ausdrücklich inaktiv;
- Artikel ausdrücklich aufgrund der Qualität gesperrt.

Potenziell kritische Attribute wie Wirkstoff, Wirkstärke, Konzentration, Darreichungsform,
Verabreichungsweg, Größe, Gauge, Charrière, Sterilität, Material und Kompatibilität werden geprüft.
Abweichungen führen jedoch standardmäßig zu `review`, bis action medeor genaue Substitutions- und
Ausschlussregeln freigibt. Das JSON-Regelwerk macht spätere Änderungen ausdrücklich prüfbar und
versionierbar.

Die Attributvokabulare für Medikamente und Ausrüstung bleiben getrennt, obwohl beide dieselbe
allgemeine Vergleichs-Engine verwenden.

## 10. Verpackungs- und Erfüllungsnachweise

Sind Menge, Einheiten pro Verpackung und Einheiten vergleichbar, berechnet das Framework sowohl die
abgerundete als auch die aufgerundete Verpackungsoption.

Beispiel: 50 angefragte Stück, 12 Stück pro Verpackung.

```text
4 Verpackungen = 48 Stück (Differenz -2)
5 Verpackungen = 60 Stück (Differenz +10)
```

Es wird keine Option empfohlen, bevor action medeor eine Rundungsregel bestätigt. Exakte Divisionen
können automatisch ausgewählt werden, weil sie keine Rundungsentscheidung erfordern.

Der Bestand wird nur verglichen, wenn seine Einheit beziehungsweise Bezugsbasis ausdrücklich mit der
angefragten Menge oder der ausgewählten Verpackungsanzahl kompatibel ist. Die aktuelle Bestandsliste
bestätigt diese Basis nicht. Deshalb ist der ehrliche Standard `unknown`, während die Rohwerte für
Bestand, eingehende Bestellungen, Einkaufsanfragen und gebundene Aufträge erhalten bleiben. Das
Framework implementiert keine erfundene Formel für den verfügbaren Angebotsbestand.

## 11. Rangfolge

Die anfängliche Rangfolge ist lexikografisch und deterministisch statt eine undurchsichtige gewichtete
Summe zu verwenden:

1. Ausgeschlossene Kandidaten werden entfernt.
2. Vollständig bestandene Kandidaten stehen vor Kandidaten mit Prüf- oder Warnstatus.
3. Exakte Artikelreferenzen erhalten Vorrang.
4. Eine stärkere Übereinstimmung strukturierter Attribute erhält Vorrang.
5. Der zusammengeführte Suchrang löst verbleibende Unterschiede bei der Produkteignung auf.
6. Vergleichbare operative Nachweise können ansonsten gleichwertige Kandidaten unterscheiden.
7. Die Artikelnummer dient als stabiler letzter Gleichstandsentscheid.

Das Framework zeichnet getrennte Komponenten auf (`exact_reference`, lexikalisch, Vektor, Historie,
`attribute_match_ratio`, RRF). Sie sind Rangfolgenachweise und keine Wahrscheinlichkeiten für die
Richtigkeit. Preis, Verfügbarkeit, Zuverlässigkeit, Aktualität, Haltbarkeit, Dokumentation und
Partnerpräferenz besitzen ausdrückliche Erweiterungspunkte; fehlende oder nicht vergleichbare
Nachweise werden jedoch niemals in null umgewandelt.

Top K ist standardmäßig zehn und wird durch den Anfragevertrag begrenzt. Weniger Kandidaten sind ein
gültiges Ergebnis.

## 12. Nachvollziehbarkeit

Jeder zurückgegebene Kandidat enthält:

- Suchkanal, Rang, Score und Details;
- strukturierte Regelergebnisse;
- übereinstimmende und abweichende Werte;
- Verpackungsoptionen;
- einen konservativ bewerteten Verfügbarkeitsstatus;
- Warnungen zu fehlenden Daten;
- den Herkunftsnachweis des Katalogeintrags;
- Versionen von Algorithmus, Regelwerk, Quelle und Embedding-Modell über den übergeordneten
  Matching-Lauf.

Es wird kein Feld namens „Konfidenz in Prozent“ ausgegeben. Konfidenz erfordert einen gelabelten
Kalibrierungsdatensatz.

## 13. Persistenzmodell

### Quellen und Katalog

- `source_snapshots`: unveränderliche Quellenidentität, Prüfsumme, Erfassungszeit und Fundstelle;
- `catalog_items`: stabile Artikelidentität und maßgeblicher Status;
- `catalog_item_versions`: Beschreibungen, Attribute, Verpackung und Inhalts-Hash je Quellversion;
- `inventory_snapshots`: zeitabhängige Bestandsrohwerte, getrennt von den Produktinhalten.

Diese Trennung verhindert, dass häufige Bestandsänderungen unnötige Neuberechnungen der Embeddings
auslösen.

### Embeddings

- `embedding_models`: Anbieter, Name, Version, Dimensionen und Distanzmetrik;
- `product_embeddings`: Katalogversion, Modell, Inhalts-Hash und Vektor.

Bei der aktuellen Kataloggröße ist eine exakte Kosinussuche der Standard. pgvector verhindert die
Notwendigkeit eines zweiten Datenbankdienstes und erhält gleichzeitig einen sauberen Skalierungspfad.

### Historie und Feedback

- `historical_offers`: normalisierte, mit Zeitstempel versehene Beschaffungsnachweise;
- `match_runs`: unveränderliche Anfrage- und Ergebnisdaten einschließlich Versionen und Status;
- `match_candidates`: normalisierte Prüfdatensätze für Analysen auf Kandidatenebene;
- `match_decisions`: Entscheidung für Annahme, Alternative, manuelle Zuordnung, keine Zuordnung oder
  erforderliche Beschaffung;
- `partner_preferences`: ausdrücklich vorgeschlagene, freigegebene oder außer Kraft gesetzte
  Präferenzen mit Quellnachweis.

`partner_preferences` wird niemals automatisch aus Klicks befüllt.

## 14. API

Die Matching-API ist bewusst unabhängig vom Figma-UI-Branch.

### Einen Lauf anlegen

```text
POST /api/v1/match-runs
```

Akzeptiert `MatchRequestV1`. Die API speichert zunächst `running`, führt das Matching aus und speichert
anschließend das vollständige Ergebnis oder markiert den Lauf mit einer Fehlermeldung als `failed`.
Eine Anfrage kann optional ein vorberechnetes Anfrage-Embedding und eine registrierte Modell-ID
enthalten.

### Einen Lauf lesen

```text
GET /api/v1/match-runs/{match_run_id}
```

Gibt das ursprünglich gespeicherte Ergebnis zurück und führt keine erneute Bewertung mit aktuellen
Daten durch.

### Eine Entscheidung aufzeichnen

```text
POST /api/v1/match-decisions
```

Unterstützt die Annahme eines Vorschlags, die Auswahl einer Alternative, eine manuelle Zuordnung,
keine Zuordnung und erforderliche Beschaffung. Alternativen erfordern eine Begründung. Vorgeschlagene
und alternative Kandidaten werden gegen den gespeicherten Matching-Lauf geprüft.

## 15. Rückfallverhalten

- Kein Vektoranbieter oder keine Vektordaten: Exakte, lexikalische und historische Suche laufen
  weiter.
- Keine Historie: Das Katalog-Matching wird fortgesetzt.
- Fehlende Verpackung: Der Kandidat bleibt mit einer Verpackungswarnung erhalten.
- Unbestätigte Bestandsbasis: Die Verfügbarkeit bleibt unbekannt.
- Keine geeigneten Kandidaten: Der Lauf endet erfolgreich mit einer leeren Kandidatenliste.
- Abweichende Modelldimensionen: Es entsteht ein sichtbarer Konfigurationsfehler und der Lauf schlägt
  fehl.
- Datenbankfehler: Der fehlgeschlagene Lauf wird nach Möglichkeit gespeichert; es wird kein
  erfundenes Teilergebnis erzeugt.

## 16. Teststrategie

Unit- und API-Tests prüfen:

- strikte Validierung der Datenverträge;
- das Verhalten der exakten, lexikalischen, vektorbasierten und historischen Suche;
- Deduplizierung durch RRF;
- konservative Regelergebnisse;
- den Ausschluss inaktiver Artikel, auch wenn Verlauf oder Vektorsuche sie finden;
- nachvollziehbare Verpackungsberechnung;
- unbekannte Bestandsbasis;
- deterministische Rangfolge und Rückfallverhalten;
- den Abruf gespeicherter Matching-Läufe und die Validierung von Entscheidungen.

Ein optionaler Integrationstest verwendet eine migrierte PostgreSQL-/pgvector-Datenbank, um die echte
Zuordnung von Katalog-JSON und die exakte Kosinussuche zu prüfen. Er wird mit gesetzter Variable
`MATCHING_TEST_DATABASE_URL` ausgeführt.

Künftig freigegebene Benchmarkdaten sollten Recall@1/3/10, MRR, Abdeckung, Latenz, Abweichungsrate und
vor allem Verletzungen harter Regeln messen; das Ziel für Letztere ist null. Echte Partnerdateien
werden nicht als Test-Fixtures in das Repository aufgenommen.

## 17. Integrationsgrenze zur Figma-UI

Diese Implementierung verändert keine Frontend-Datei und keinen UI-Branch. Die vorherige UI-Analyse
hat folgende Anforderungen an einen künftigen Adapter ergeben:

- algorithmische Vorschläge von menschlichen Bestätigungen unterscheiden;
- einen Ranking-Score nicht als kalibrierte Konfidenz darstellen;
- Verfügbarkeit differenzierter als mit `lowStock: bool` abbilden;
- Warnungen, Regeln, Herkunftsnachweise und Verpackungsinformationen anzeigen;
- manuelle Zuordnung, keine Zuordnung, erforderliche Beschaffung und die Begründung einer Abweichung
  unterstützen;
- in der Auftragsübersicht ausschließlich bestätigte Entscheidungen verwenden.

Ein künftiger UI-spezifischer Antwort-Mapper kann `MatchRunResponseV1` übersetzen, ohne die
Matching-Domänenlogik zu verändern.

## 18. Ontologien und Wissensgraphen

Ein kontrolliertes Vokabular oder eine Ontologie kann bereits vor einer Graphdatenbank nützlich
werden. Versionierte Konzept-IDs können Synonyme, Übersetzungen, Darreichungsformen,
Verabreichungswege, Einheiten, Produktfamilien und extern freigegebene Klassifikationen normalisieren,
während jeder ursprüngliche Wert erhalten bleibt. Diese Konzept-IDs können in den bestehenden
relationalen Attributen gespeichert werden und sowohl Suche als auch Regelprüfungen verbessern.

Eine Graphdatenbank reduziert die Matching-Latenz nicht automatisch und ersetzt weder Vektor- noch
lexikalische oder strukturierte Indizes. Bei der aktuellen Größenordnung würde sie zusätzliche
betriebliche Komplexität ohne nachgewiesene mehrstufige Abfrage verursachen. Das relationale Schema
bildet die benötigten direkten Beziehungen bereits ab, und pgvector begrenzt die semantische Suche.
Ein separater Wissensgraph wird erst dann sinnvoll, wenn gemessene Anwendungsfälle wiederholt Pfade wie
Produkt → kompatibles Gerät → freigegebenes Ersatzprodukt → Lieferant → Zielbeschränkung benötigen und
diese Beziehungen maßgebliche Verantwortliche sowie Versionierungsregeln besitzen.

## 19. Bewusst zurückgestellte Arbeiten

| Zurückgestellt | Warum jetzt nicht | Bereits vorbereitet | Aktivierungsbedingung |
|---|---|---|---|
| Excel-/PDF-/E-Mail-Extraktion | Anderes Team und anderer Fehlerbereich | Strikte Verträge und Herkunftsnachweise | Payload des Extraktors vereinbart |
| Outlook-Connector | Benötigt Postfach, Entra, Berechtigungen und Betrieb | Outlook-Quellentypen und Fundstellen | Postfach und Zugriff freigegeben |
| Business-Central-Live-Synchronisierung | Kein bestätigter API- oder Schemazugriff | Katalog-/Bestandsschnittstellen und Snapshots | Schreibgeschützte API und Datenwörterbuch |
| SharePoint-Live-Synchronisierung | Ordnerumfang und maßgeblicher Status ungeklärt | Historienschnittstelle und Herkunftsnachweise | Umfang und Berechtigungen freigegeben |
| Lieferanten-Bestands-APIs | Lieferanten und Semantik unbekannt | Lieferantenfähige Kandidatengrenze | Eine freigegebene Pilotquelle |
| Produktives Embedding-Modell | Kein gelabelter Vergleich und keine Governance-Entscheidung | Anbieterport, Registry und pgvector | Benchmark-Gewinner und Datenschutzfreigabe |
| HNSW/IVFFlat | 646 Zeilen benötigen keine approximative Suche | pgvector-Speicherung | p95-Latenz- oder Skalenschwelle überschritten |
| Cross-Encoder | Zusätzliche Latenz und MLOps ohne gemessenen Nutzen | Grenze für erneute Rangbildung | Recall@10 gut, Reihenfolge messbar schwach |
| LLM als Entscheider | Halluzinationen, Kosten, Datenschutz und Reproduzierbarkeit | Nicht im kritischen Pfad | Eng begrenzter, nicht sicherheitskritischer Anwendungsfall |
| Online-Lernen | Positionsverzerrung und unsichere Feedbackschleifen | Unveränderliche Anzeige- und Entscheidungsdaten | Ohne starke Kontrollen nicht vorgesehen |
| Learning-to-Rank | Zu wenige saubere Labels | Merkmals- und benchmarkfähige Datensätze | Ausreichender geprüfter zeitlicher Datensatz |
| Konfidenz in Prozent | Suchscores sind keine Wahrscheinlichkeiten | Nachweise und Prüfstatus | Erfolgreiche Kalibrierungsstudie |
| Wissensgraph-Datenbank | Keine nachgewiesene mehrstufige Abfragelast | Relationale Konzepte und Beziehungen ergänzbar | Wiederholte komplexe Graphabfragen |
| Vollständige ATC-/SNOMED-/GMDN-Zuordnung | Zweck, Lizenz und Zuordnung unbestätigt | Optionale externe Codefelder später | Entscheidung über action-medeor-Standard |
| Harte Substitutionsregeln | Klinische oder technische Gleichwertigkeit unbestätigt | Versioniertes Regelwerk | Ausdrückliche Freigabe der Fachverantwortlichen |
| Formel für verfügbaren Angebotsbestand | Semantik der Bestandsfelder ungeklärt | Getrennte Rohdaten-Snapshots | Maßgebliche Formel bestätigt |
| Automatischer Ausschluss nach Haltbarkeit | Regel für Ankunft, Empfang und Route ungeklärt | Felder und Regel-Schnittstelle | Bestätigte Regel und Chargendaten |
| Preisbasierte Rangfolge | Währung, Basis, Fracht und Gültigkeit unvollständig | Erweiterungspunkt für vergleichbare Nachweise | Normalisierter Preisvertrag |
| Zuverlässigkeitswert für Lieferanten | Keine Ergebnishistorie oder Mindeststichprobe | Ergebnisfähiges Historienmodell | Genügend abgeschlossene Beschaffungen |
| Automatische Verpackungsrundung | Richtung hängt vom Arbeitsablauf ab | Beide nachvollziehbaren Optionen | Bestätigte Regel oder Profil |
| Vom Benutzer einstellbare Gewichte | Risiko für Sicherheit und Reproduzierbarkeit | Versioniertes serverseitiges Regelwerk | Freigegebene begrenzte Szenarioprofile |
| Automatische Bestätigung | Prototyp ist eine Entscheidungsunterstützung | Expliziter Entscheidungsendpunkt | Enger nachgewiesener Fall und Freigabe |
| Änderungen an der Figma-UI | Heutiger Umfang ist ausschließlich Matching | Stabile API und Integrationshinweise | Separate UI-Integrationsaufgabe |
| Dashboards, Prognosen und Angebote | Außerhalb der Abnahme des Kern-Matchings | Prüfbare historische Daten | Stabiles Matching-MVP |
| Microservices/Kafka | Betrieblicher Mehraufwand für aktuelles Team und Volumen | Schnittstellen und klare Modulgrenzen | Nachgewiesener Bedarf bei Bereitstellung oder Teamgröße |

## 20. Einen produktiven Embedding-Anbieter ergänzen

1. `EmbeddingProvider` mit einer stabilen `model_id` implementieren.
2. Anbieter, Name, Version und Dimensionen in `embedding_models` registrieren.
3. Kanonischen Katalogtext und Inhalts-Hash erzeugen.
4. Vektoren stapelweise nur für fehlende Paare aus `(Katalogversion, Modell)` erzeugen.
5. Vektoren in `product_embeddings` speichern.
6. Anhand eines zurückgehaltenen mehrsprachigen Benchmarks evaluieren.
7. In der aufrufenden Anwendung ausschließlich die freigegebene Modell-ID aktivieren.

Vektoren verschiedener Modell-IDs oder Dimensionen dürfen niemals verglichen werden.

## 21. Eine Regel ergänzen oder ändern

1. Eine maßgebliche fachliche Entscheidung und Beispiele einholen.
2. Das Attribut im Extraktionsvertrag ergänzen oder normalisieren.
3. Einen versionierten Regeleintrag (`on_missing`, `on_mismatch`) ergänzen.
4. Tests für Übereinstimmung, Abweichung, fehlende Werte und Grenzfälle ergänzen.
5. Eine Regressionsmenge aus bestehenden gelabelten Fällen erstellen.
6. Eine neue Regelversion veröffentlichen; niemals die Bedeutung einer bereits aufgezeichneten alten
   Version verändern.

## 22. Fertigstellungskriterien für dieses Fundament

- keine Änderungen am Frontend;
- strikte V1-Verträge und Herkunftsnachweise;
- vier Suchkanäle und deterministische Zusammenführung;
- konservative Regeln und Verpackungsberechnung;
- deterministische Top 10 mit nachvollziehbaren Nachweisen;
- pgvector-Migration und Adapter für die exakte Vektorsuche;
- unveränderliche Läufe, Kandidaten und Entscheidungen;
- definiertes Rückfallverhalten;
- Unit-/API-Tests und echter pgvector-Integrationstest;
- Ruff und pytest ohne Befunde;
- kurze und ausführliche Matching-Dokumentation.
