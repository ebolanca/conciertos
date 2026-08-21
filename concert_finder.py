import unicodedata
import json
import logging
import urllib.parse
from pathlib import Path
from datetime import datetime
import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ConcertFinder:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.target_city = self.config["concerts"].get("target_city", "Madrid").strip().lower()
        self.target_country = self.config["concerts"].get("target_country_code", "ES")
        self.include_unsold = self.config["concerts"].get("include_unsold_events", True)
        self.tm_api_key = self.config["concerts"].get("ticketmaster_api_key", "").strip()

        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.artists_file = self.data_dir / "artists.json"
        self.concerts_file = self.data_dir / "concerts.json"

    def load_qualified_artists(self) -> list:
        if not self.artists_file.exists():
            logger.warning("No existe artists.json. Ejecuta primero artist_scanner.py")
            return []
        
        with open(self.artists_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return list(data.get("qualified_artists", {}).keys())

    def _query_bandsintown(self, artist: str) -> list:
        events = self._fetch_bandsintown_events(artist)
        if not events:
            norm_artist = "".join(c for c in unicodedata.normalize("NFKD", artist) if not unicodedata.combining(c))
            if norm_artist != artist:
                events = self._fetch_bandsintown_events(norm_artist)
        return events

    def _fetch_bandsintown_events(self, artist: str) -> list:
        events = []
        try:
            encoded_artist = urllib.parse.quote(artist)
            url = f"https://rest.bandsintown.com/artists/{encoded_artist}/events?app_id=js_1.0.0"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for ev in data:
                        venue = ev.get("venue", {})
                        city = venue.get("city", "").strip().lower()
                        country = venue.get("country", "").strip()
                        
                        if self.target_city in city or "madrid" in city:
                            event_date_raw = ev.get("datetime", "")
                            on_sale_raw = ev.get("on_sale_datetime", "")
                            
                            # Determinar estado de la venta
                            now_str = datetime.now().isoformat()
                            if on_sale_raw and on_sale_raw > now_str:
                                status = "PENDIENTE_VENTA"
                            else:
                                status = "ENTRADAS_A_LA_VENTA"

                            offers = ev.get("offers", [])
                            ticket_url = offers[0].get("url") if offers else ev.get("url", "")
                            
                            events.append({
                                "id": f"bit_{ev.get('id')}",
                                "artist": artist,
                                "title": f"Concierto de {artist} en Madrid",
                                "venue": venue.get("name", "Madrid Venue"),
                                "city": "Madrid",
                                "event_date": event_date_raw,
                                "ticket_sale_date": on_sale_raw or event_date_raw,
                                "ticket_url": ticket_url,
                                "status": status,
                                "source": "Bandsintown"
                            })
        except Exception as e:
            logger.debug(f"Error consultando Bandsintown para {artist}: {e}")
        
        return events

    def _query_ticketmaster(self, artist: str) -> list:
        events = []
        if not self.tm_api_key:
            return events
            
        try:
            url = "https://app.ticketmaster.com/discovery/v2/events.json"
            params = {
                "apikey": self.tm_api_key,
                "keyword": artist,
                "city": "Madrid",
                "countryCode": self.target_country,
                "sort": "date,asc"
            }
            resp = requests.get(url, params=params, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                embedded = data.get("_embedded", {})
                raw_events = embedded.get("events", [])
                for ev in raw_events:
                    sales = ev.get("sales", {}).get("public", {})
                    start_sale = sales.get("startDateTime", "")
                    
                    dates = ev.get("dates", {}).get("start", {})
                    event_date = dates.get("dateTime", dates.get("localDate", ""))
                    
                    venues = ev.get("_embedded", {}).get("venues", [])
                    venue_name = venues[0].get("name", "Madrid Venue") if venues else "Madrid Venue"
                    
                    now_str = datetime.now().isoformat()
                    if start_sale and start_sale > now_str:
                        status = "PENDIENTE_VENTA"
                    else:
                        status = "ENTRADAS_A_LA_VENTA"

                    events.append({
                        "id": f"tm_{ev.get('id')}",
                        "artist": artist,
                        "title": ev.get("name", f"Concierto de {artist} en Madrid"),
                        "venue": venue_name,
                        "city": "Madrid",
                        "event_date": event_date,
                        "ticket_sale_date": start_sale or event_date,
                        "ticket_url": ev.get("url", ""),
                        "status": status,
                        "source": "Ticketmaster"
                    })
        except Exception as e:
            logger.debug(f"Error consultando Ticketmaster para {artist}: {e}")
            
        return events

    def search_concerts(self) -> dict:
        artists = self.load_qualified_artists()
        logger.info(f"Buscando conciertos en Madrid para {len(artists)} artistas cualificados...")
        
        # Cargar conciertos guardados previamente para no perder estados como 'COMPRADO'
        existing_concerts = {}
        if self.concerts_file.exists():
            try:
                with open(self.concerts_file, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                    for item in old_data.get("concerts", []):
                        existing_concerts[item["id"]] = item
            except Exception:
                pass

        all_found = {}
        for artist in artists:
            bit_events = self._query_bandsintown(artist)
            tm_events = self._query_ticketmaster(artist)
            
            combined = bit_events + tm_events
            for ev in combined:
                ev_id = ev["id"]
                # Preservar estado 'COMPRADO' o 'IGNORADO' si existía
                if ev_id in existing_concerts and existing_concerts[ev_id].get("status") == "COMPRADO":
                    ev["status"] = "COMPRADO"
                all_found[ev_id] = ev

        concert_list = list(all_found.values())
        
        result = {
            "last_check": datetime.now().isoformat(),
            "target_city": "Madrid",
            "total_concerts_found": len(concert_list),
            "pending_sale_count": len([c for c in concert_list if c["status"] == "PENDIENTE_VENTA"]),
            "on_sale_count": len([c for c in concert_list if c["status"] == "ENTRADAS_A_LA_VENTA"]),
            "bought_count": len([c for c in concert_list if c["status"] == "COMPRADO"]),
            "concerts": sorted(concert_list, key=lambda x: x.get("event_date", ""))
        }

        with open(self.concerts_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Búsqueda finalizada. Conciertos en Madrid encontrados: {len(concert_list)}")
        return result

if __name__ == "__main__":
    finder = ConcertFinder()
    res = finder.search_concerts()
    print(json.dumps(res, indent=2, ensure_ascii=False))
