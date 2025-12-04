# ooir-rss-feeds

Das Repository besteht aus drei Hauptkomponenten, die zusammenarbeiten, um Paper-Trend-Daten von der OOIR-API in ein abonnierbares RSS-Format umzuwandeln.

---

## 1. Der Workflow-Steuerer: `generate_rss.yml` ⚙️

Diese Datei ist der Bauplan für die **Automatisierung** und läuft auf GitHub Actions. Ihre Hauptaufgabe ist es, sicherzustellen, dass das Hauptskript (`ooir_rss_monitor.py`) **täglich** ausgeführt wird und die Ergebnisse im Repository speichert.

| Sektion | Zweck | Details |
| :--- | :--- | :--- |
| **`on:`** | **Auslöser** | Definiert, wann der Workflow startet. Hier täglich um Mitternacht UTC (`cron: '0 0 * * *'`) und manuell über `workflow_dispatch`. |
| **`jobs: build`** | **Ausführungsumgebung** | Definiert die Schritte. Erlaubt Schreibzugriff auf das Repository (`permissions: contents: write`) und nutzt eine Ubuntu-Maschine. |
| **`steps`** | **Prozessschritte** | 1. Code auschecken. 2. Python 3 einrichten. 3. Abhängigkeiten (`requests`) installieren. 4. Das Hauptskript **`ooir_rss_monitor.py`** ausführen, wobei das GitHub Secret `OOIR_EMAIL` als Umgebungsvariable übergeben wird. |
| **`Commit and push changes`** | **Speichern** | Konfiguriert den Git-Benutzer und committet die neu generierten RSS-Feeds und die Index-Seite (`docs/`) zurück ins Repository. |

---

## 2. Der Hauptprozessor: `ooir_rss_monitor.py` 🧠

Dies ist das Herzstück Ihres Projekts. Die Klasse **`OOIRTrendMonitor`** ist dafür verantwortlich, die Rohdaten von externen APIs abzurufen und sie in das standardisierte RSS-Format zu transformieren.

### Hauptfunktionen:

| Methode | Zweck | Details |
| :--- | :--- | :--- |
| `_fetch_data_from_api` | **OOIR-Daten abrufen** | Stellt eine Anfrage an die **OOIR API** (`ooir.org/v2/api.php`) unter Verwendung der aktuellen Tagesdaten und der spezifischen `field`/`category` Parameter. Gibt die rohe JSON-Liste der Paper-Trends zurück. |
| `_fetch_article_metadata_from_doi` | **Metadaten abrufen** | Ruft die **Crossref API** auf, um umfassende Artikeldetails (vollständiger Titel, Autoren, Journal, Veröffentlichungsdatum) anhand der **DOI** zu erhalten. Dies reichert die oft minimalistischen OOIR-Trenddaten an. |
| `_create_rss_item` | **RSS-Item erstellen** | Kombiniert die Daten aus OOIR und Crossref, um ein einzelnes RSS `<item>` Element zu erstellen. Stellt sicher, dass das Datum korrekt im GMT-Format für RSS (`pubDate`) vorliegt. |
| `generate_rss_feed` | **Feed erstellen und speichern** | Generiert die vollständige RSS-XML-Datei für eine bestimmte Kategorie und speichert sie als `.xml` im **`docs`**-Verzeichnis. |
| `generate_index_html` | **Index-Seite** | Erstellt eine einfache **`index.html`** mit Hyperlinks zu allen generierten RSS-Feeds, um das Auffinden zu erleichtern. |
| `main` | **Steuerlogik** | Definiert die festen medizinischen **Kategorien** (z. B. `Rehabilitation`, `Sport Sciences`, `Medical Informatics`), für die Feeds generiert werden sollen, und durchläuft diese, um die API-Aufrufe und Feed-Generierung zu starten. |

---

## 3. Das Dienstprogramm: `feed_manager.py` 📊

Dieses Skript dient zur **Wartung, Diagnose und Berichterstattung** und ist **nicht** Teil des automatischen täglichen GitHub-Workflows. Es müsste separat manuell ausgeführt werden, um die Zustandsprüfungen durchzuführen.

| Methode | Zweck |
| :--- | :--- |
| `get_feed_stats` | Sammelt Statistiken, indem es alle generierten `.xml`-Feeds analysiert (z. B. Anzahl der Items, Dateigröße) und sie mit den Verlaufsdaten aus dem `.history`-Ordner abgleicht. |
| `print_stats` / `export_stats` | Formatiert diese gesammelten Statistiken und gibt sie auf der Konsole aus oder exportiert sie als JSON-Datei. |
| `clean_old_history` | Verwaltet die Größe der Historie, indem es alte Papers (standardmäßig älter als 30 Tage) aus den `.pkl`-Verlaufsdateien entfernt. |
| `reset_feed` | Löscht die Verlaufsdatei (`*_history.pkl`) für einen bestimmten Feed, was effektiv dazu führt, dass dieser Feed beim nächsten Lauf als "neu" behandelt wird. |
| `validate_feeds` | Führt eine formale Prüfung aller `.xml`-Dateien durch, um sicherzustellen, dass sie technisch korrekt und gültig sind (Überprüfung auf `<rss>`, `<channel>`, `<title>` etc.). |

Zusammenfassend lässt sich sagen: Die **`.yml`**-Datei ist der Timer und die Startrampe. Die **`ooir_rss_monitor.py`**-Datei ist der Motor, der die Daten holt, veredelt und die Feeds baut. Die **`feed_manager.py`**-Datei ist Ihr Inspektions- und Wartungswerkzeug.
