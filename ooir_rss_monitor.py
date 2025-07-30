import os
import requests
import json
import datetime
import xml.etree.ElementTree as ET
import re
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

    def _fetch_data_from_api(self, field: str, category: Optional[str] = None) -> Optional[dict]:
        """
        Holt Trenddaten für ein spezifisches Feld und optional eine Kategorie von der OOIR API.
        """
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        api_url = f"https://ooir.org/api.php?email={self.email}&type=paper-trends&day={today_str}&field={requests.utils.quote(field)}"
        
        if category:
            api_url += f"&category={requests.utils.quote(category)}"
        
        print(f"DEBUG: Fetching from API: {api_url}")

        try:
            response = requests.get(api_url, timeout=30)
            response.raise_for_status()  # Löst einen HTTPError für schlechte Antworten (4xx oder 5xx) aus
            
            data = response.json()
            return data

        except requests.exceptions.RequestException as e:
            print(f"FEHLER beim Abrufen von Daten für Feld '{field}' und Kategorie '{category or 'N/A'}': {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"API-Antwort Status: {e.response.status_code}")
                print(f"API-Antwort Text: {e.response.text}")
            return None
        except json.JSONDecodeError as e:
            print(f"FEHLER: Ungültige JSON-Antwort für Feld '{field}' und Kategorie '{category or 'N/A'}': {e}")
            print(f"Rohe API-Antwort, die keine gültige JSON war: {response.text}")
            return None

    def _create_rss_item(self, article: dict) -> ET.Element:
        """Erstellt ein RSS-Item-Element aus einem Artikel-Dictionary."""
        item = ET.Element("item")

        title = ET.SubElement(item, "title")
        title_text = article.get("title", "Kein Titel verfügbar")
        # Optional: Entfernen von HTML-Tags aus dem Titel, falls vorhanden
        title.text = re.sub(r'<[^>]*>', '', title_text) 

        link = ET.SubElement(item, "link")
        link.text = article.get("DOI", "") or article.get("link", "") # DOI oder anderer Link

        description = ET.SubElement(item, "description")
        desc_text = f"Journal: {article.get('journal', 'N/A')}\n"
        desc_text += f"Published: {article.get('published_date', 'N/A')}\n" # Sicherstellen, dass der korrekte Key verwendet wird
        desc_text += f"Authors: {', '.join(article.get('authors', ['N/A']))}\n" if article.get('authors') else ""
        desc_text += f"Abstract: {re.sub(r'<[^>]*>', '', article.get('abstract', ''))}\n" if article.get('abstract') else ""
        # Formatieren Sie die Beschreibung, um sie besser lesbar für RSS-Reader zu machen (z.B. als CDATA)
        description.text = desc_text
        
        guid = ET.SubElement(item, "guid")
        guid.text = article.get("DOI", "") or f"ooir-paper-{article.get('published_date', '')}-{re.sub(r'[^a-zA-Z0-9]', '', article.get('title', ''))[:20]}"
        guid.set("isPermaLink", "false") # Nicht dauerhaft, da sich DOI ändern könnte (falls kein DOI)

        pub_date = ET.SubElement(item, "pubDate")
        try:
            # Versuche, das Datum aus 'published_date' zu parsen, sonst fallback auf 'published' oder aktuelles Datum
            date_str = article.get("published_date") or article.get("published")
            if date_str:
                pub_datetime = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                pub_date.text = pub_datetime.strftime("%a, %d %b %Y %H:%M:%S GMT")
            else:
                pub_date.text = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        except ValueError:
            pub_date.text = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

        return item

    def generate_rss_feed(self, full_category_name: str, field_name: str, category_param: Optional[str], papers_data: Optional[dict]):
        """Generiert einen RSS-Feed für eine bestimmte Kategorie mit den bereitgestellten Daten."""
        rss = ET.Element("rss", version="2.0")
        channel = ET.SubElement(rss, "channel")

        ET.SubElement(channel, "title").text = f"OOIR Trends: {full_category_name}"
        ET.SubElement(channel, "description").text = f"Aktuelle Paper-Trends im Bereich {full_category_name} von OOIR (nur neue und kürzlich hinzugefügte Papers)"
        ET.SubElement(channel, "link").text = "https://ooir.org"
        ET.SubElement(channel, "language").text = "en-us"
        
        current_time_gmt = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        ET.SubElement(channel, "pubDate").text = current_time_gmt
        ET.SubElement(channel, "lastBuildDate").text = current_time_gmt

        articles_for_feed = []
        if papers_data and "papers" in papers_data:
            articles_for_feed = papers_data["papers"][:self.max_items]

        if not articles_for_feed:
            error_item = ET.SubElement(channel, "item")
            ET.SubElement(error_item, "title").text = f"⚠️ Fehler beim Abrufen von {full_category_name}"
            ET.SubElement(error_item, "description").text = "Fehler: Keine neuen Artikel oder ungültige API-Antwort."
            ET.SubElement(error_item, "link").text = "https://ooir.org"
            # Generiere eine eindeutige GUID für den Fehlerfall
            error_guid_base = f"ooir-error-{re.sub(r'[^a-zA-Z0-9_]', '', field_name).lower()}"
            if category_param:
                error_guid_base += f"-{re.sub(r'[^a-zA-Z0-9_]', '', category_param).lower()}"
            ET.SubElement(error_item, "guid").text = f"{error_guid_base}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            ET.SubElement(error_item, "pubDate").text = current_time_gmt
        else:
            for article in articles_for_feed:
                channel.append(self._create_rss_item(article))

        # Dateiname anpassen (z.B. computer_science.xml oder clinical_medicine_rheumatology.xml)
        if category_param:
            # Kombiniere Feld und Kategorie für den Dateinamen
            filename_base = f"{re.sub(r'[^a-zA-Z0-9_]', '', field_name).lower()}_{re.sub(r'[^a-zA-Z0-9_]', '', category_param).lower()}"
        else:
            # Nur Feld für den Dateinamen (z.B. Multidisciplinary)
            filename_base = re.sub(r'[^a-zA-Z0-9_]', '', field_name).lower()

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
            if category_param:
                filename = f"{re.sub(r'[^a-zA-Z0-9_]', '', field_name).lower()}_{re.sub(r'[^a-zA-Z0-9_]', '', category_param).lower()}.xml"
            else:
                filename = f"{re.sub(r'[^a-zA-Z0-9_]', '', field_name).lower()}.xml"
            
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

    # Liste der zu überwachenden Kategorien: (Vollständiger Name, Field-Parameter, Category-Parameter (optional))
    # Beachten Sie die genaue Schreibweise der 'Field' und 'Category' Parameter,
    # da diese direkt an die API gehen.
    categories_to_monitor = [
        ("Biology & Biochemistry", "Biology & Biochemistry", None), # Hauptkategorie
        ("Clinical Medicine", "Clinical Medicine", None), # Hauptkategorie
        ("Clinical Medicine (Endocrinology & Metabolism)", "Clinical Medicine", "Endocrinology & Metabolism"),
        ("Clinical Medicine (Integrative & Complementary Medicine)", "Clinical Medicine", "Integrative & Complementary Medicine"),
        ("Clinical Medicine (Medical Informatics)", "Clinical Medicine", "Medical Informatics"),
        ("Clinical Medicine (Medicine, General & Internal)", "Clinical Medicine", "Medicine, General & Internal"),
        ("Clinical Medicine (Medicine, Research & Experimental)", "Clinical Medicine", "Medicine, Research & Experimental"),
        ("Clinical Medicine (Nutrition & Dietetics)", "Clinical Medicine", "Nutrition & Dietetics"),
        ("Clinical Medicine (Orthopedics)", "Clinical Medicine", "Orthopedics"),
        ("Clinical Medicine (Pharmacology & Pharmacy)", "Clinical Medicine", "Pharmacology & Pharmacy"),
        ("Clinical Medicine (Rehabilitation)", "Clinical Medicine", "Rehabilitation"),
        ("Clinical Medicine (Rheumatology)", "Clinical Medicine", "Rheumatology"),
        ("Clinical Medicine (Sport Sciences)", "Clinical Medicine", "Sport Sciences"),
        ("Computer Science", "Computer Science", None), # Hauptkategorie
        ("Economics & Business", "Economics & Business", None), # Hauptkategorie
        ("Multidisciplinary", "Multidisciplinary", None), # Hauptkategorie
        ("Philosophy & Religion", "Philosophy & Religion", None), # Hauptkategorie
        ("Psychiatry & Psychology", "Psychiatry & Psychology", None), # Hauptkategorie
        ("Social Sciences", "Social Sciences", None), # Hauptkategorie
        # Beispiel für Unterkategorie, wie Sie es im API-Beispiel hatten:
        ("Social Sciences (Political Science)", "Social Sciences", "Political Science"),
    ]

    # Gehe durch jede Kategorie und hole Daten spezifisch für diese Kategorie
    for full_name, field_name, category_param in categories_to_monitor:
        papers_data = monitor._fetch_data_from_api(field=field_name, category=category_param)
        monitor.generate_rss_feed(full_name, field_name, category_param, papers_data)

    # Generiere die index.html nur einmal am Ende
    monitor.generate_index_html(categories_to_monitor)

    print("Alle RSS-Feeds und Index-Seite wurden generiert.")

if __name__ == "__main__":
    main()
