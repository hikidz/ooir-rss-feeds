#!/usr/bin/env python3
"""
RSS Feed Manager Utility
Hilfswerkzeug zur Verwaltung der OOIR RSS Feeds
"""

import os
import pickle
import json
from datetime import datetime, timedelta
import argparse
from typing import Dict, List
import xml.etree.ElementTree as ET

class FeedManager:
    def __init__(self, rss_dir: str = "rss_feeds"):
        self.rss_dir = rss_dir
        self.history_dir = os.path.join(rss_dir, ".history")
        
    def get_feed_stats(self) -> Dict:
        """
        Sammelt Statistiken über alle RSS Feeds
        
        Returns:
            Dictionary mit Feed-Statistiken
        """
        stats = {
            "feeds": {},
            "total_feeds": 0,
            "total_papers": 0,
            "last_updated": None
        }
        
        # RSS-Dateien analysieren
        if os.path.exists(self.rss_dir):
            for filename in os.listdir(self.rss_dir):
                if filename.endswith('.xml'):
                    feed_path = os.path.join(self.rss_dir, filename)
                    feed_name = filename.replace('.xml', '').replace('_', ' ').title()
                    
                    try:
                        # XML-Datei parsen
                        tree = ET.parse(feed_path)
                        root = tree.getroot()
                        
                        items = root.findall('.//item')
                        new_items = [item for item in items if '🆕' in item.find('title').text]
                        
                        # Letzte Aktualisierung
                        last_build = root.find('.//lastBuildDate')
                        last_update = last_build.text if last_build is not None else "Unbekannt"
                        
                        stats["feeds"][feed_name] = {
                            "filename": filename,
                            "total_items": len(items),
                            "new_items": len(new_items),
                            "last_updated": last_update,
                            "file_size": os.path.getsize(feed_path)
                        }
                        
                        stats["total_papers"] += len(items)
                        
                    except ET.ParseError as e:
                        print(f"Fehler beim Parsen von {filename}: {e}")
                        
            stats["total_feeds"] = len(stats["feeds"])
        
        # Verlaufsdaten analysieren
        if os.path.exists(self.history_dir):
            for filename in os.listdir(self.history_dir):
                if filename.endswith('_history.pkl'):
                    field_name = filename.replace('_history.pkl', '').replace('_', ' ').title()
                    history_path = os.path.join(self.history_dir, filename)
                    
                    try:
                        with open(history_path, 'rb') as f:
                            history = pickle.load(f)
                            
                        if field_name in stats["feeds"]:
                            stats["feeds"][field_name]["known_papers"] = len(history.get("known_papers", set()))
                            stats["feeds"][field_name]["history_updated"] = history.get("last_updated", "Unbekannt")
                            
                    except (pickle.PickleError, FileNotFoundError) as e:
                        print(f"Fehler beim Lesen der Verlaufsdaten {filename}: {e}")
        
        return stats
    
    def print_stats(self) -> None:
        """
        Gibt Feed-Statistiken auf der Konsole aus
        """
        stats = self.get_feed_stats()
        
        print("=" * 60)
        print("📊 OOIR RSS FEED STATISTIKEN")
        print("=" * 60)
        print(f"Anzahl Feeds: {stats['total_feeds']}")
        print(f"Gesamte Papers: {stats['total_papers']}")
        print()
        
        if stats["feeds"]:
            print("📄 EINZELNE FEEDS:")
            print("-" * 60)
            for feed_name, data in stats["feeds"].items():
                print(f"{feed_name}")
                print(f"  📁 Datei: {data['filename']}")
                print(f"  📄 Items: {data['total_items']} (davon {data['new_items']} neu)")
                print(f"  💾 Größe: {data['file_size']:,} Bytes")
                print(f"  🕒 Aktualisiert: {data.get('last_updated', 'Unbekannt')}")
                if 'known_papers' in data:
                    print(f"  📚 Bekannte Papers: {data['known_papers']}")
                print()
        else:
            print("❌ Keine RSS-Feeds gefunden!")
    
    def export_stats(self, output_file: str = "feed_stats.json") -> None:
        """
        Exportiert Statistiken als JSON-Datei
        
        Args:
            output_file: Pfad zur Ausgabedatei
        """
        stats = self.get_feed_stats()
        
        # DateTime-Objekte für JSON serialisierbar machen
        def serialize_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, default=serialize_datetime, ensure_ascii=False)
        
        print(f"✅ Statistiken exportiert nach: {output_file}")
    
    def clean_old_history(self, days: int = 30) -> None:
        """
        Bereinigt alte Verlaufsdaten
        
        Args:
            days: Alter in Tagen, ab dem Daten gelöscht werden
        """
        if not os.path.exists(self.history_dir):
            print("❌ Kein Verlaufsverzeichnis gefunden!")
            return
        
        cutoff_date = datetime.now() - timedelta(days=days)
        cleaned_count = 0
        
        for filename in os.listdir(self.history_dir):
            if filename.endswith('_history.pkl'):
                history_path = os.path.join(self.history_dir, filename)
                
                try:
                    with open(history_path, 'rb') as f:
                        history = pickle.load(f)
                    
                    # Alte Papers aus der Historie entfernen
                    old_papers = []
                    for paper in history.get("papers_data", []):
                        added_date_str = paper.get("_added_date", "")
                        if added_date_str:
                            added_date = datetime.fromisoformat(added_date_str)
                            if added_date < cutoff_date:
                                old_papers.append(paper)
                    
                    if old_papers:
                        # Neue History ohne alte Papers
                        history["papers_data"] = [
                            p for p in history.get("papers_data", [])
                            if p not in old_papers
                        ]
                        
                        # Known papers Set aktualisieren
                        history["known_papers"] = {
                            p.get("_hash", "") for p in history["papers_data"]
                        }
                        
                        # Aktualisierte History speichern
                        with open(history_path, 'wb') as f:
                            pickle.dump(history, f)
                        
                        cleaned_count += len(old_papers)
                        print(f"🧹 {filename}: {len(old_papers)} alte Papers entfernt")
                
                except (pickle.PickleError, ValueError) as e:
                    print(f"❌ Fehler bei {filename}: {e}")
        
        print(f"✅ Bereinigung abgeschlossen. {cleaned_count} alte Papers entfernt.")
    
    def reset_feed(self, field: str) -> None:
        """
        Setzt einen bestimmten Feed zurück (löscht Verlaufsdaten)
        
        Args:
            field: Name des Wissenschaftsbereichs
        """
        filename = field.replace(" ", "_").replace("&", "and").lower() + "_history.pkl"
        history_path = os.path.join(self.history_dir, filename)
        
        if os.path.exists(history_path):
            os.remove(history_path)
            print(f"✅ Verlaufsdaten für '{field}' zurückgesetzt")
        else:
            print(f"❌ Keine Verlaufsdaten für '{field}' gefunden")
    
    def validate_feeds(self) -> None:
        """
        Validiert alle RSS-Feeds auf Korrektheit
        """
        print("🔍 VALIDIERE RSS-FEEDS...")
        print("-" * 40)
        
        valid_feeds = 0
        invalid_feeds = 0
        
        if os.path.exists(self.rss_dir):
            for filename in os.listdir(self.rss_dir):
                if filename.endswith('.xml'):
                    feed_path = os.path.join(self.rss_dir, filename)
                    
                    try:
                        tree = ET.parse(feed_path)
                        root = tree.getroot()
                        
                        # Basic RSS-Struktur prüfen
                        if root.tag != "rss":
                            raise Exception("Kein gültiger RSS-Feed (fehlendes <rss> Element)")
                        
                        channel = root.find('channel')
                        if channel is None:
                            raise Exception("Kein <channel> Element gefunden")
                        
                        title = channel.find('title')
                        if title is None or not title.text:
                            raise Exception("Kein Titel gefunden")
                        
                        items = channel.findall('item')
                        
                        print(f"✅ {filename}: {len(items)} Items, Titel: '{title.text}'")
                        valid_feeds += 1
                        
                    except ET.ParseError as e:
                        print(f"❌ {filename}: XML-Parsing-Fehler: {e}")
                        invalid_feeds += 1
                    except Exception as e:
                        print(f"❌ {filename}: {e}")
                        invalid_feeds += 1
        
        print("-" * 40)
        print(f"✅ Gültige Feeds: {valid_feeds}")
        print(f"❌ Ungültige Feeds: {invalid_feeds}")


def main():
    parser = argparse.ArgumentParser(description="OOIR RSS Feed Manager")
    parser.add_argument("--dir", default="rss_feeds", help="RSS-Feed Verzeichnis")
    
    subparsers = parser.add_subparsers(dest="command", help="Verfügbare Befehle")
    
    # Stats Befehl
    stats_parser = subparsers.add_parser("stats", help="Zeigt Feed-