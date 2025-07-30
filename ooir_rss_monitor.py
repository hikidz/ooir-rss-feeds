#!/usr/bin/env python3
"""
OOIR Trend Monitoring mit RSS Feed Generator
Erstellt RSS Feeds für verschiedene Wissenschaftsbereiche basierend auf OOIR API Daten
"""

import requests
import json
from datetime import datetime, timedelta
from xml.etree.ElementTree import Element, SubElement, tostring
import xml.dom.minidom
import os
import time
import logging
import hashlib
import pickle
from typing import Dict, List, Optional, Set, Tuple

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OOIRTrendMonitor:
    def __init__(self, email: str, output_dir: str = "rss_feeds", max_items: int = 50):
        """
        Initialisiert den OOIR Trend Monitor
        
        Args:
            email: Ihre E-Mail-Adresse für die API
            output_dir: Verzeichnis für die RSS-Dateien
            max_items: Maximale Anzahl Items pro Feed
        """
        self.email = email
        self.base_url = "https://ooir.org/api.php"
        self.output_dir = output_dir
        self.max_items = max_items
        
        # Wissenschaftsbereiche und Kategorien die überwacht werden sollen
        # Jeder Eintrag ist ein Tupel (field, category)
        self.fields_and_categories = [
            ("Biology & Biochemistry", None), # None bedeutet 'all' für die API
            ("Clinical Medicine", None),
            ("Computer Science", None),
            ("Economics & Business", None),
            ("Multidisciplinary", None),
            ("Philosophy & Religion", None),
            ("Psychiatry and Psychology", None),
            ("Social Sciences", None),
            # Zusätzliche spezifische Kategorien für Clinical Medicine
            ("Clinical Medicine", "Integrative & Complementary Medicine"),
            ("Clinical Medicine", "Endocrinology & Metabolism"),
            ("Clinical Medicine", "Medical Informatics"),
            ("Clinical Medicine", "Medicine, General & Internal"),
            ("Clinical Medicine", "Medicine, Research & Experimental"),
            ("Clinical Medicine", "Nutrition & Dietetics"),
            ("Clinical Medicine", "Orthopedics"),
            ("Clinical Medicine", "Pharmacology & Pharmacy"),
            ("Clinical Medicine", "Rehabilitation"),
            ("Clinical Medicine", "Rheumatology"),
            ("Clinical Medicine", "Sport Sciences")
        ]
        
        # Output-Verzeichnis erstellen
        os.makedirs(output_dir, exist_ok=True)
        
        # Verzeichnis für Verlaufsdaten
        self.history_dir = os.path.join(output_dir, ".history")
        os.makedirs(self.history_dir, exist_ok=True)
        
    def get_paper_hash(self, paper: Dict) -> str:
        """
        Erstellt eindeutigen Hash für ein Paper basierend auf Titel und Autoren
        
        Args:
            paper: Paper-Dictionary
            
        Returns:
            SHA256 Hash als String
        """
        title = paper.get("title", "")
        authors = str(paper.get("authors", []))
        content = f"{title}|{authors}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def get_feed_identifier(self, field: str, category: Optional[str]) -> str:
        """
        Erstellt einen eindeutigen Bezeichner für einen Feed basierend auf Feld und optionaler Kategorie.
        Wird für Dateinamen und Historie verwendet.
        """
        if category:
            return f"{field}_{category}".replace(" ", "_").replace("&", "and").replace(",", "").lower()
        return field.replace(" ", "_").replace("&", "and").lower()

    def load_feed_history(self, identifier: str) -> Dict:
        """
        Lädt die Verlaufsdaten für einen Feed
        
        Args:
            identifier: Eindeutiger Bezeichner des Feeds
            
        Returns:
            Dictionary mit bekannten Papers und Metadaten
        """
        filename = identifier + "_history.pkl"
        filepath = os.path.join(self.history_dir, filename)
        
        try:
            with open(filepath, 'rb') as f:
                return pickle.load(f)
        except (FileNotFoundError, EOFError, pickle.PickleError):
            return {
                "known_papers": set(),
                "papers_data": [],
                "last_updated": None
            }
    
    def save_feed_history(self, identifier: str, history: Dict) -> None:
        """
        Speichert die Verlaufsdaten für einen Feed
        
        Args:
            identifier: Eindeutiger Bezeichner des Feeds
            history: Verlaufsdaten-Dictionary
        """
        filename = identifier + "_history.pkl"
        filepath = os.path.join(self.history_dir, filename)
        
        history["last_updated"] = datetime.now()
        
        with open(filepath, 'wb') as f:
            pickle.dump(history, f)
    
    def merge_papers(self, identifier: str, new_papers: List[Dict]) -> List[Dict]:
        """
        Führt neue Papers mit dem bestehenden Feed zusammen
        
        Args:
            identifier: Eindeutiger Bezeichner des Feeds
            new_papers: Liste neuer Papers von der API
            
        Returns:
            Kombinierte Liste aller Papers (neue + bestehende)
        """
        # Verlaufsdaten laden
        history = self.load_feed_history(identifier)
        known_hashes = history["known_papers"]
        existing_papers = history["papers_data"]
        
        # Neue Papers identifizieren
        truly_new_papers = []
        new_hashes_from_api = set() # Hashes der Papers, die in der aktuellen API-Antwort sind
        
        for paper in new_papers:
            paper_hash = self.get_paper_hash(paper)
            paper["_hash"] = paper_hash # Sicherstellen, dass Hash im Paper gespeichert ist
            new_hashes_from_api.add(paper_hash)
            
            if paper_hash not in known_hashes:
                # Paper ist wirklich neu
                paper["_is_new"] = True
                paper["_added_date"] = datetime.now().isoformat()
                truly_new_papers.append(paper)
                logger.info(f"Neues Paper in {identifier}: {paper.get('title', 'Unbekannt')[:50]}...")
        
        # Bestehende Papers, die in der neuen API-Antwort enthalten sind oder noch jung genug sind, behalten
        updated_existing = []
        for paper in existing_papers:
            paper_hash = paper.get("_hash", "")
            if paper_hash in new_hashes_from_api:
                # Paper ist noch aktuell und wird im neuen Feed erscheinen, nicht mehr "neu" markieren
                paper["_is_new"] = False
                updated_existing.append(paper)
            else:
                # Paper ist nicht mehr in den aktuellen Trends der API-Antwort
                # Aber wir behalten es für eine Woche, um sicherzustellen, dass es nicht zu schnell verschwindet
                added_date_str = paper.get("_added_date", "")
                if added_date_str:
                    try:
                        added_date = datetime.fromisoformat(added_date_str)
                        if (datetime.now() - added_date).days < 7:
                            paper["_is_new"] = False # Es ist nicht mehr _neu_ in diesem Lauf, aber weiterhin sichtbar
                            updated_existing.append(paper)
                    except ValueError:
                        logger.warning(f"Ungültiges Datumsformat für Paper {paper.get('title')}: {added_date_str}")
                        # Wenn Datum ungültig, Paper vorsichtshalber behalten
                        updated_existing.append(paper)
                else:
                    # Wenn kein added_date, Paper behalten (älter als 7 Tage wird später entfernt)
                    updated_existing.append(paper)
        
        # Kombinieren: Neue Papers zuerst, dann bestehende, dann deduplizieren
        combined_papers_raw = truly_new_papers + updated_existing
        
        # Deduplizieren basierend auf Hash und eine bevorzugte Reihenfolge beibehalten (neu zuerst)
        deduplicated_papers = []
        seen_hashes = set()
        
        # Priorisiere wirklich neue Papers ganz oben
        for paper in truly_new_papers:
            if paper.get("_hash") not in seen_hashes:
                deduplicated_papers.append(paper)
                seen_hashes.add(paper.get("_hash"))
        
        # Füge dann bestehende Papers hinzu, die noch nicht hinzugefügt wurden
        for paper in updated_existing:
            if paper.get("_hash") not in seen_hashes:
                paper["_is_new"] = False # Bestehende Papers sind nicht mehr "neu"
                deduplicated_papers.append(paper)
                seen_hashes.add(paper.get("_hash"))

        # Auf maximale Anzahl begrenzen
        combined_papers_final = deduplicated_papers[:self.max_items]
        
        # Verlaufsdaten aktualisieren
        all_hashes_in_final_list = {p.get("_hash", "") for p in combined_papers_final}
        history["known_papers"] = all_hashes_in_final_list
        history["papers_data"] = combined_papers_final
        self.save_feed_history(identifier, history)
        
        logger.info(f"{identifier}: {len(truly_new_papers)} neue Papers, {len(combined_papers_final)} gesamt im Feed.")
        
        return combined_papers_final
    
    def get_paper_trends(self, field: str, date: Optional[str] = None, category: Optional[str] = None) -> Dict:
        """
        Ruft Paper-Trends für ein bestimmtes Feld und optional eine Kategorie ab
        
        Args:
            field: Wissenschaftsbereich
            date: Datum im Format YYYY-MM-DD (Standard: heute)
            category: Optionale Kategorie
            
        Returns:
            API-Antwort als Dictionary
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
            
        params = {
            "email": self.email,
            "type": "paper-trends",
            "day": date,
            "field": field
        }
        if category:
            params["category"] = category
        
        identifier = self.get_feed_identifier(field, category)

        try:
            logger.info(f"Abrufen von Trends für {field}{f' ({category})' if category else ''} am {date}")
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            # Prüfen ob gültige JSON-Antwort
            try:
                data = response.json()
                return data
            except json.JSONDecodeError:
                logger.warning(f"Keine gültige JSON-Antwort für {identifier}: {response.text[:200]}")
                return {"error": "Invalid JSON response", "field": field, "category": category}
                
        except requests.RequestException as e:
            logger.error(f"API-Fehler für {identifier}: {e}")
            return {"error": str(e), "field": field, "category": category}
            
    def create_rss_feed(self, field: str, category: Optional[str], papers_data: Dict) -> str:
        """
        Erstellt einen RSS-Feed aus den Paper-Daten (mit intelligentem Update)
        
        Args:
            field: Wissenschaftsbereich
            category: Optionale Kategorie
            papers_data: Daten von der API
            
        Returns:
            RSS-Feed als XML-String
        """
        identifier = self.get_feed_identifier(field, category)
        display_name = f"{field}{f' ({category})' if category else ''}"

        # Root RSS Element
        rss = Element("rss", version="2.0")
        channel = SubElement(rss, "channel")
        
        # Channel-Informationen
        title = SubElement(channel, "title")
        title.text = f"OOIR Trends: {display_name}"
        
        description = SubElement(channel, "description")
        description.text = f"Aktuelle Paper-Trends im Bereich {display_name} von OOIR (nur neue und kürzlich hinzugefügte Papers)"
        
        link = SubElement(channel, "link")
        link.text = "https://ooir.org"
        
        language = SubElement(channel, "language")
        language.text = "en-us"
        
        pub_date = SubElement(channel, "pubDate")
        pub_date.text = datetime.now().strftime("%a, %d %b %Y %H:%M:%S GMT")
        
        last_build_date = SubElement(channel, "lastBuildDate")
        last_build_date.text = datetime.now().strftime("%a, %d %b %Y %H:%M:%S GMT")
        
        # Papers verarbeiten und mit Verlauf zusammenführen
        if "error" not in papers_data and "papers" in papers_data:
            raw_papers = papers_data.get("papers", [])
            combined_papers = self.merge_papers(identifier, raw_papers) # Hier identifier verwenden
            
            # RSS Items erstellen
            for paper in combined_papers:
                item = SubElement(channel, "item")
                
                # Titel mit NEW-Marker für wirklich neue Papers
                item_title = SubElement(item, "title")
                title_text = paper.get("title", "Unbekannter Titel")
                if paper.get("_is_new", False):
                    title_text = f"🆕 {title_text}"
                item_title.text = title_text
                
                item_description = SubElement(item, "description")
                authors = paper.get("authors", [])
                citations = paper.get("citations", 0)
                altmetric = paper.get("altmetric_score", 0)
                added_date = paper.get("_added_date", "")
                
                desc_text = f"Autoren: {', '.join(authors[:3])}{'...' if len(authors) > 3 else ''}"
                desc_text += f" | Zitationen: {citations} | Altmetric Score: {altmetric}"
                if paper.get("_is_new", False):
                    desc_text += " | 🆕 NEU hinzugefügt"
                elif added_date:
                    try:
                        added = datetime.fromisoformat(added_date).strftime("%d.%m.%Y")
                        desc_text += f" | Hinzugefügt: {added}"
                    except ValueError:
                        desc_text += f" | Hinzugefügt: Datum unbekannt"
                
                item_description.text = desc_text
                
                item_link = SubElement(item, "link")
                item_link.text = paper.get("url", "https://ooir.org")
                
                # Eindeutige GUID basierend auf Paper-Hash
                item_guid = SubElement(item, "guid")
                paper_hash = paper.get("_hash", self.get_paper_hash(paper))
                item_guid.text = f"ooir-{identifier}-{paper_hash}"
                
                # Publikationsdatum: Hinzufügungsdatum oder aktuelles Datum
                item_pub_date = SubElement(item, "pubDate")
                if added_date:
                    try:
                        pub_datetime = datetime.fromisoformat(added_date)
                    except ValueError:
                        pub_datetime = datetime.now() # Fallback
                else:
                    pub_datetime = datetime.now()
                item_pub_date.text = pub_datetime.strftime("%a, %d %b %Y %H:%M:%S GMT")
        
        elif "error" in papers_data:
            # Fehler-Item hinzufügen
            item = SubElement(channel, "item")
            
            item_title = SubElement(item, "title")
            item_title.text = f"⚠️ Fehler beim Abrufen von {display_name}"
            
            item_description = SubElement(item, "description")
            item_description.text = f"Fehler: {papers_data['error']}"
            
            item_link = SubElement(item, "link")
            item_link.text = "https://ooir.org"
            
            item_guid = SubElement(item, "guid")
            item_guid.text = f"ooir-error-{identifier}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            item_pub_date = SubElement(item, "pubDate")
            item_pub_date.text = datetime.now().strftime("%a, %d %b %Y %H:%M:%S GMT")
        
        # XML formatieren
        rough_string = tostring(rss, encoding='unicode')
        reparsed = xml.dom.minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
    
    def save_rss_feed(self, identifier: str, rss_content: str) -> str:
        """
        Speichert den RSS-Feed in eine Datei
        
        Args:
            identifier: Eindeutiger Bezeichner des Feeds
            rss_content: RSS-XML-Inhalt
            
        Returns:
            Pfad zur gespeicherten Datei
        """
        # Dateiname erstellen (URL-freundlich)
        filename = identifier + ".xml"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(rss_content)
            
        logger.info(f"RSS-Feed gespeichert: {filepath}")
        return filepath
    
    def run_monitoring(self, date: Optional[str] = None) -> Dict[str, str]:
        """
        Führt das komplette Monitoring für alle Felder/Kategorien durch
        
        Args:
            date: Datum für die Abfrage (Standard: heute)
            
        Returns:
            Dictionary mit Anzeigename -> Dateipfad Zuordnungen
        """
        results = {}
        
        logger.info("Starte OOIR Trend Monitoring...")
        
        for field, category in self.fields_and_categories:
            identifier = self.get_feed_identifier(field, category)
            display_name = f"{field}{f' ({category})' if category else ''}"
            try:
                # API-Daten abrufen
                papers_data = self.get_paper_trends(field, date, category)
                
                # RSS-Feed erstellen
                rss_content = self.create_rss_feed(field, category, papers_data)
                
                # RSS-Feed speichern
                filepath = self.save_rss_feed(identifier, rss_content)
                results[display_name] = filepath
                
                # Kurze Pause zwischen API-Calls, um Rate-Limits zu vermeiden
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Fehler bei {display_name}: {e}")
                results[display_name] = f"ERROR: {e}"
        
        logger.info(f"Monitoring abgeschlossen. {len(results)} RSS-Feeds erstellt.")
        return results
    
    def create_index_html(self, results: Dict[str, str]) -> None:
        """
        Erstellt eine HTML-Index-Seite mit Links zu allen RSS-Feeds
        
        Args:
            results: Dictionary mit Anzeigename -> Dateipfad Zuordnungen
        """
        html_content = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OOIR Trend Monitoring - RSS Feeds</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        h1 { color: #333; }
        .feed-list { list-style-type: none; padding: 0; }
        .feed-item { 
            background: #f5f5f5; 
            margin: 10px 0; 
            padding: 15px; 
            border-radius: 5px;
            border-left: 4px solid #007cba;
        }
        .feed-link { text-decoration: none; color: #007cba; font-weight: bold; }
        .feed-link:hover { text-decoration: underline; }
        .timestamp { color: #666; font-size: 0.9em; }
        .error { border-left-color: #dc3545; }
    </style>
</head>
<body>
    <h1>OOIR Trend Monitoring - RSS Feeds</h1>
    <p>Automatisch generierte RSS-Feeds für verschiedene Wissenschaftsbereiche und Kategorien.</p>
    <p class="timestamp">Letzte Aktualisierung: """ + datetime.now().strftime("%d.%m.%Y %H:%M:%S") + """</p>
    
    <ul class="feed-list">
"""
        
        for display_name, filepath in results.items():
            if not filepath.startswith("ERROR"):
                filename = os.path.basename(filepath)
                html_content += f"""        <li class="feed-item">
            <a href="{filename}" class="feed-link">{display_name}</a>
            <br><small>RSS Feed für aktuelle Paper-Trends</small>
        </li>
"""
            else:
                html_content += f"""        <li class="feed-item error">
            <span class="feed-link">{display_name}</span>
            <br><small style="color: #dc3545;">Fehler: {filepath}</small>
        </li>
"""
        
        html_content += """    </ul>
    
    <h2>Verwendung</h2>
    <p>Kopieren Sie die URLs der RSS-Feeds in Ihren bevorzugten RSS-Reader:</p>
    <ul>
"""
        
        for display_name, filepath in results.items():
            if not filepath.startswith("ERROR"):
                filename = os.path.basename(filepath)
                html_content += f'        <li><code>http://ihr-server.de/rss_feeds/{filename}</code></li>\n'
        
        html_content += """    </ul>
</body>
</html>"""
        
        index_path = os.path.join(self.output_dir, "index.html")
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"Index-Seite erstellt: {index_path}")


def main():
    """
    Hauptfunktion - Beispiel für die Verwendung
    """
    # WICHTIG: Ersetzen Sie dies durch Ihre echte E-Mail-Adresse
    # Oder besser: Verwenden Sie eine Umgebungsvariable wie bei GitHub Actions vorgeschlagen.
    EMAIL = os.environ.get("OOIR_EMAIL", "ihre.email@beispiel.de")
    if EMAIL == "ihre.email@beispiel.de":
        logger.warning("Bitte ändern Sie die E-Mail-Adresse im Skript oder als Umgebungsvariable 'OOIR_EMAIL'.")
    
    # Monitor initialisieren
    monitor = OOIRTrendMonitor(email=EMAIL)
    
    # Monitoring durchführen
    results = monitor.run_monitoring()
    
    # Index-Seite erstellen
    monitor.create_index_html(results)
    
    # Ergebnisse ausgeben
    print("\n=== OOIR Trend Monitoring Ergebnisse ===")
    for display_name, filepath in results.items():
        print(f"{display_name}: {filepath}")
    
    print(f"\nAlle RSS-Feeds wurden im Verzeichnis '{monitor.output_dir}' gespeichert.")
    print("Öffnen Sie die 'index.html' Datei für eine Übersicht aller Feeds.")


if __name__ == "__main__":
    main()