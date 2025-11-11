import os
import requests
import json
import datetime
import xml.etree.ElementTree as ET
import re
import time # Für Verzögerungen zwischen API-Aufrufen
from typing import Optional, List, Tuple

class OOIRTrendMonitor:
    def __init__(self, email: str, output_dir: str = "docs", max_items: int = 50):
        self.email = email
        self.output_dir = output_dir
        self.max_items = max_items
        self._ensure_output_directory_exists()

    def _ensure_output_directory_exists(self):
        """Stellt sicher, dass das Ausgabe-Verzeichnis existiert."""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            print(f"Verzeichnis '{self.output_dir}' erstellt.")

    def _fetch_data_from_api(self, field: str, category: Optional[str] = None) -> Optional[list]:
        """
        Holt Trenddaten für ein spezifisches Feld und optional eine Kategorie von der OOIR API.
        Erwartet eine Liste von Artikeln als JSON-Antwort.
        """
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        # **ÄNDERUNG: Die API-Basis-URL wurde auf 'v2/api.php' aktualisiert**
        api_url = f"https://ooir.org/v2/api.php?email={self.email}&type=paper-trends&day={today_str}&field={requests.utils.quote(field)}"
        
        if category:
            api_url += f"&category={requests.utils.quote(category)}"
        
        print(f"DEBUG: Fetching from OOIR API: {api_url}")

        try:
            response = requests.get(api_url, timeout=30)
            response.raise_for_status()  # Löst einen HTTPError für schlechte Antworten (4xx oder 5xx) aus
            
            data = response.json()
            if isinstance(data, list): # OOIR API gibt direkt eine Liste zurück
                return data
            # Die API scheint jetzt direkt eine Liste von Artikeln zurückzugeben, aber dieser Fall bleibt als robustere Abdeckung
            elif isinstance(data, dict) and "papers" in data and isinstance(data["papers"], list): # Falls sie doch mal unter 'papers' sind
                return data["papers"]
            else:
                print(f"WARNUNG: Unerwartetes Datenformat von OOIR API für '{field}' und '{category or 'N/A'}'. Erwartet Liste oder Dict mit 'papers'. Erhalten: {data}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"FEHLER beim Abrufen von Daten von OOIR API für Feld '{field}' und Kategorie '{category or 'N/A'}': {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"API-Antwort Status: {e.response.status_code}")
                # Die API-Antwort kann nicht immer JSON sein, daher den Text ausgeben
                print(f"API-Antwort Text: {e.response.text}")
            return None
        except json.JSONDecodeError as e:
            print(f"FEHLER: Ungültige JSON-Antwort von OOIR API für Feld '{field}' und Kategorie '{category or 'N/A'}': {e}")
            # Die rohe Antwort ausgeben, um das Problem besser analysieren zu können
            if 'response' in locals() and response is not None:
                 print(f"Rohe OOIR API-Antwort, die keine gültige JSON war: {response.text}")
            return None

    def _fetch_article_metadata_from_doi(self, doi: str) -> Optional[dict]:
        """
        Holt vollständige Artikelmetadaten (Titel, Autoren, Journal) von der Crossref API anhand der DOI.
        """
        if not doi or doi == "N/A":
            return None

        crossref_url = f"https://api.crossref.org/works/{requests.utils.quote(doi)}"
        print(f"DEBUG: Fetching metadata from Crossref API for DOI: {doi}")

        # Wichtig: Crossref empfiehlt, eine Kontakt-E-Mail im User-Agent anzugeben,
        # um im "Polite Pool" zu landen und höhere Rate Limits zu erhalten.
        headers = {
            "User-Agent": f"OOIR-RSS-Monitor/1.0 (mailto:{self.email})"
        }

        try:
            response = requests.get(crossref_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data and data.get("status") == "ok" and "message" in data:
                return data["message"]
            else:
                print(f"WARNUNG: Crossref API lieferte keine Metadaten für DOI {doi}. Antwort: {data}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"FEHLER beim Abrufen von Metadaten von Crossref API für DOI {doi}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Crossref API-Antwort Status: {e.response.status_code}")
                print(f"Crossref API-Antwort Text: {e.response.text}")
            return None
        except json.JSONDecodeError as e:
            print(f"FEHLER: Ungültige JSON-Antwort von Crossref API für DOI {doi}: {e}")
            if 'response' in locals() and response is not None:
                 print(f"Rohe Crossref API-Antwort, die keine gültige JSON war: {response.text}")
            return None

    def _create_rss_item(self, article: dict) -> ET.Element:
        """
        Erstellt ein RSS-Item-Element aus einem Artikel-Dictionary, 
        angereichert mit Daten von Crossref.
        """
        item = ET.Element("item")

        doi = article.get("doi", "N/A")
        crossref_metadata = None
        if doi != "N/A":
            crossref_metadata = self._fetch_article_metadata_from_doi(doi)
            time.sleep(0.1) # Kurze Pause, um Crossref Rate Limits einzuhalten (Polite Pool)

        title_text = f"DOI: {doi} (Rank: {article.get('rank', 'N/A')})"
        if crossref_metadata and "title" in crossref_metadata and crossref_metadata["title"]:
            # Crossref Titel ist oft eine Liste, nehmen den ersten Eintrag
            title_text = crossref_metadata["title"][0] if isinstance(crossref_metadata["title"], list) else crossref_metadata["title"]
            title_text = re.sub(r'<[^>]*>', '', title_text) # HTML-Tags entfernen

        title = ET.SubElement(item, "title")
        title.text = title_text

        link = ET.SubElement(item, "link")
        if crossref_metadata and "URL" in crossref_metadata:
            link.text = crossref_metadata["URL"] # Direktlink zum Artikel, falls von Crossref geliefert
        elif doi != "N/A":
            link.text = f"https://doi.org/{doi}" # Fallback auf DOI-Resolver
        else:
            link.text = "https://ooir.org" # Letzter Fallback-Link

        description = ET.SubElement(item, "description")
        desc_parts = []
        desc_parts.append(f"Feld: {article.get('field', 'N/A')}")
        desc_parts.append(f"Kategorie: {article.get('category', 'N/A')}")
        desc_parts.append(f"Score: {article.get('score', 'N/A')}")
        
        if crossref_metadata:
            if "author" in crossref_metadata:
                authors = []
                for author in crossref_metadata["author"]:
                    if "given" in author and "family" in author:
                        authors.append(f"{author['given']} {author['family']}")
                    elif "name" in author: # Manchmal ist nur ein "name" Feld vorhanden
                        authors.append(author["name"])
                if authors:
                    desc_parts.append(f"Autoren: {', '.join(authors)}")

            if "container-title" in crossref_metadata and crossref_metadata["container-title"]:
                journal_title = crossref_metadata["container-title"][0] if isinstance(crossref_metadata["container-title"], list) else crossref_metadata["container-title"]
                desc_parts.append(f"Journal: {journal_title}")
            
            # **FIX: Robusteres Parsen für published date-parts im Description-Feld**
            if "published" in crossref_metadata and "date-parts" in crossref_metadata["published"]:
                date_parts_pub = crossref_metadata["published"]["date-parts"][0]
                if date_parts_pub:
                    try:
                        year = date_parts_pub[0] if len(date_parts_pub) >= 1 else 1
                        month = date_parts_pub[1] if len(date_parts_pub) >= 2 else 1
                        day = date_parts_pub[2] if len(date_parts_pub) >= 3 else 1
                        
                        # Sicherstellen, dass Monat und Tag gültig sind, bevor datetime.date erstellt wird
                        if not (1 <= month <= 12): month = 1
                        if not (1 <= day <= 31): day = 1 # Vereinfachte Prüfung, genaue Prüfung erfordert Kenntnis des Monats
                        
                        # **Korrektur:** Das Jahr muss mindestens 1 sein
                        if year < 1: year = 1
                        
                        pub_date_crossref = datetime.date(year, month, day)
                        desc_parts.append(f"Veröffentlicht: {pub_date_crossref.strftime('%Y-%m-%d')}")
                    except ValueError as e:
                        print(f"WARNUNG: Fehler beim Parsen des Crossref Published Datums für DOI {doi} (Beschreibung): {e}")
            
            if "abstract" in crossref_metadata and crossref_metadata["abstract"]:
                abstract_text = re.sub(r'<[^>]*>', '', crossref_metadata["abstract"]) # HTML-Tags entfernen
                desc_parts.append(f"Abstract: {abstract_text}")
        
        desc_parts.append(f"DOI: {doi}")
        desc_parts.append(f"ISSN: {article.get('issn', 'N/A')}")
        desc_parts.append(f"Tag der Erhebung (OOIR): {article.get('day', 'N/A')}")

        description.text = "\n".join(desc_parts)
        
        guid = ET.SubElement(item, "guid")
        guid.text = f"ooir-trend-{doi}-{article.get('day', '')}-{article.get('rank', '')}"
        guid.set("isPermaLink", "false")

        pub_date_str = None
        # **FIX: Robusteres Parsen für issued date-parts im pubDate-Feld**
        if crossref_metadata and "issued" in crossref_metadata and "date-parts" in crossref_metadata["issued"]:
            try:
                date_parts_issued = crossref_metadata["issued"]["date-parts"][0]
                year = date_parts_issued[0] if len(date_parts_issued) >= 1 else 1900
                month = date_parts_issued[1] if len(date_parts_issued) >= 2 else 1
                day = date_parts_issued[2] if len(date_parts_issued) >= 3 else 1
                
                # Sicherstellen, dass Monat und Tag gültig sind
                if not (1 <= month <= 12): month = 1
                if not (1 <= day <= 31): day = 1
                
                dt_obj = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
                pub_date_str = dt_obj.strftime("%a, %d %b %Y %H:%M:%S GMT")
            except Exception as e:
                print(f"WARNUNG: Fehler beim Parsen des Crossref Issued Datums für DOI {doi}: {e}")

        # Fallback auf OOIR-Datum, wenn Crossref-Datum nicht verfügbar oder fehlerhaft
        if not pub_date_str:
            try:
                date_str_ooir = article.get("day")
                if date_str_ooir:
                    pub_datetime_ooir = datetime.datetime.strptime(date_str_ooir, "%Y-%m-%d")
                    pub_date_str = pub_datetime_ooir.replace(tzinfo=datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
            except ValueError:
                pass # OOIR Datum unvollständig oder fehlerhaft
        
        # Letzter Fallback auf aktuelle Zeit
        if not pub_date_str:
            pub_date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

        pub_date = ET.SubElement(item, "pubDate")
        pub_date.text = pub_date_str

        return item

    def generate_rss_feed(self, full_category_name: str, field_name: str, category_param: Optional[str], papers_data: Optional[list]):
        """Generiert einen RSS-Feed für eine bestimmte Kategorie mit den bereitgestellten Daten."""
        rss = ET.Element("rss", version="2.0")
        channel = ET.SubElement(rss, "channel")

        ET.SubElement(channel, "title").text = f"OOIR Trends: {full_category_name}"
        ET.SubElement(channel, "description").text = f"Aktuelle Paper-Trends im Bereich {full_category_name} von OOIR (mit Titel und Metadaten von Crossref)"
        ET.SubElement(channel, "link").text = "https://ooir.org"
        ET.SubElement(channel, "language").text = "en-us"
        
        current_time_gmt = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        ET.SubElement(channel, "pubDate").text = current_time_gmt
        ET.SubElement(channel, "lastBuildDate").text = current_time_gmt

        articles_for_feed = []
        if papers_data: # papers_data ist jetzt direkt eine Liste von der OOIR API
            articles_for_feed = papers_data[:self.max_items]

        if not articles_for_feed:
            error_item = ET.SubElement(channel, "item")
            ET.SubElement(error_item, "title").text = f"⚠️ Keine Trends für {full_category_name} verfügbar"
            ET.SubElement(error_item, "description").text = "Die OOIR-API lieferte keine Trend-Daten für diese Kategorie an diesem Tag."
            ET.SubElement(error_item, "link").text = "https://ooir.org"
            error_guid_base = f"ooir-no-trends-{re.sub(r'[^a-zA-Z0-9_]', '', field_name).lower()}"
            if category_param:
                error_guid_base += f"-{re.sub(r'[^a-zA-Z0-9_]', '', category_param).lower()}"
            ET.SubElement(error_item, "guid").text = f"{error_guid_base}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            ET.SubElement(error_item, "pubDate").text = current_time_gmt
        else:
            for article in articles_for_feed:
                channel.append(self._create_rss_item(article))

        if category_param:
            # Ersetzt ' ' durch '_' und entfernt alle Nicht-alphanumerischen Zeichen außer '_'
            filename_base = f"{re.sub(r'[^a-zA-Z0-9_]', '', field_name.replace(' ', '_')).lower()}_{re.sub(r'[^a-zA-Z0-9_]', '', category_param.replace(' ', '_')).lower()}"
        else:
            filename_base = re.sub(r'[^a-zA-Z0-9_]', '', field_name.replace(' ', '_')).lower()

        filename = os.path.join(self.output_dir, f"{filename_base}.xml")
        
        tree = ET.ElementTree(rss)
        ET.indent(tree, space="\t", level=0)

        with open(filename, "wb") as f:
            f.write(ET.tostring(rss, encoding="utf-8", xml_declaration=True))
        print(f"RSS Feed für '{full_category_name}' unter '{filename}' generiert.")

    def generate_index_html(self, categories: List[Tuple[str, str, Optional[str]]]):
        """Generiert eine einfache index.html-Datei mit Links zu den RSS-Feeds."""
        html_content = f"""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>OOIR RSS Feeds</title>
            <style>
                body {{ font-family: sans-serif; margin: 2em; line-height: 1.6; }}
                h1 {{ color: #333; }}
                ul {{ list-style-type: none; padding: 0; }}
                li {{ margin-bottom: 0.5em; }}
                a {{ color: #007bff; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h1>OOIR Trend RSS Feeds</h1>
            <p>Abonnieren Sie die neuesten Paper-Trends von OOIR in verschiedenen Kategorien:</p>
            <ul>
        """

        for full_name, field_name, category_param in categories:
            # Der Dateiname muss identisch mit dem in generate_rss_feed sein
            if category_param:
                filename = f"{re.sub(r'[^a-zA-Z0-9_]', '', field_name.replace(' ', '_')).lower()}_{re.sub(r'[^a-zA-Z0-9_]', '', category_param.replace(' ', '_')).lower()}.xml"
            else:
                filename = f"{re.sub(r'[^a-zA-Z0-9_]', '', field_name.replace(' ', '_')).lower()}.xml"
            
            html_content += f'                <li><a href="{filename}">{full_name} RSS Feed</a></li>\n'

        html_content += """
            </ul>
            <p>
                <small>Generiert am: """ + datetime.datetime.now(datetime.timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC") + """</small>
            </p>
        </body>
        </html>
        """

        index_html_path = os.path.join(self.output_dir, "index.html")
        with open(index_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"Index-Datei unter '{index_html_path}' generiert.")


def main():
    """
    Hauptfunktion - Beispiel für die Verwendung
    """
    EMAIL = os.getenv("OOIR_EMAIL")
    
    if not EMAIL:
        print("FEHLER: OOIR_EMAIL Umgebungsvariable nicht gesetzt. Kann nicht fortfahren.")
        return

    monitor = OOIRTrendMonitor(email=EMAIL, output_dir="docs")

    # Basierend auf Ihren Hobbies (Sport/Marathon, Sportmedizin, Physikalische und Rehabilitative Medizin, Manuelle Medizin, Schmerztherapie, Medizinische Informatik)
    # habe ich einige der relevantesten Kategorien hervorgehoben und die Liste entsprechend ergänzt/überprüft.
    categories_to_monitor = [
        # Relevanz: Ihre Fachgebiete
        ("Clinical Medicine (Rehabilitation)", "Clinical Medicine", "Rehabilitation"), # Relevant: FA Physical and Rehabilitative Medicine
        ("Clinical Medicine (Orthopedics)", "Clinical Medicine", "Orthopedics"), # Relevant: Nichtoperative Orthopädie, Manuelle Medizin
        ("Clinical Medicine (Sport Sciences)", "Clinical Medicine", "Sport Sciences"), # Relevant: Sportmedizin, Marathon
        ("Clinical Medicine (Special Pain Therapy)", "Clinical Medicine", "Special Pain Therapy"), # Relevant: Spezielle Schmerztherapie (Achtung: Dies ist eine vermutete Kategorie, falls sie nicht funktioniert, müsste man die tatsächlichen Field/Category-Namen der v2 API prüfen)
        ("Clinical Medicine (Integrative & Complementary Medicine)", "Clinical Medicine", "Integrative & Complementary Medicine"), # Relevant: Akupunktur/Manuelle Medizin

        # Relevanz: Ihr Masterstudium
        ("Clinical Medicine (Medical Informatics)", "Clinical Medicine", "Medical Informatics"), # Relevant: Master Medizinische Informatik

        # Andere medizinische/allgemeine Bereiche
        ("Clinical Medicine (Medicine, General & Internal)", "Clinical Medicine", "Medicine, General & Internal"),
        ("Clinical Medicine (Medicine, Research & Experimental)", "Clinical Medicine", "Medicine, Research & Experimental"),
        ("Clinical Medicine (Nutrition & Dietetics)", "Clinical Medicine", "Nutrition & Dietetics"),
        ("Clinical Medicine (Pharmacology & Pharmacy)", "Clinical Medicine", "Pharmacology & Pharmacy"),
        ("Clinical Medicine (Rheumatology)", "Clinical Medicine", "Rheumatology"),
        ("Clinical Medicine (Endocrinology & Metabolism)", "Clinical Medicine", "Endocrinology & Metabolism"),
    ]
    # **ANMERKUNG:** Die ursprüngliche Liste wurde beibehalten, aber um eine Kategorie ergänzt, die für Ihre Spezielle Schmerztherapie relevant sein könnte.
    # Sollte die Kategorie "Special Pain Therapy" nicht funktionieren, können Sie die entsprechende Zeile entfernen.

    for full_name, field_name, category_param in categories_to_monitor:
        papers_data = monitor._fetch_data_from_api(field=field_name, category=category_param)
        monitor.generate_rss_feed(full_name, field_name, category_param, papers_data)
        time.sleep(1) # Kleine Pause zwischen den OOIR API-Aufrufen, um Server zu entlasten

    monitor.generate_index_html(categories_to_monitor)

    print("Alle RSS-Feeds und Index-Seite wurden generiert.")

if __name__ == "__main__":
    main()
