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
        self.artist_photo_cache = {}

    def _get_artist_photo(self, artist: str) -> str:
        if not artist:
            return ""
        key = artist.strip().lower()
        if key in self.artist_photo_cache:
            return self.artist_photo_cache[key]
        
        LOCAL_PHOTOS = {
            "amaral": "/artist_images/amaral.jpg",
            "alex ubago": "/artist_images/alex_ubago.jpg",
            "morat": "/artist_images/morat.jpg",
            "binomio de oro de américa": "/artist_images/binomio_de_oro.jpg",
            "binomio de oro": "/artist_images/binomio_de_oro.jpg",
            "the weeknd": "/artist_images/the_weeknd.jpg",
            "aitana": "/artist_images/aitana.jpg",
            "shakira": "/artist_images/shakira.jpg",
            "pitbull": "/artist_images/pitbull.jpg",
            "la oreja de van gogh": "/artist_images/la_oreja_de_van_gogh.jpg",
            "evanescence": "/artist_images/evanescence.jpg",
            "bryan adams": "/artist_images/bryan_adams.jpg"
        }
        for k in LOCAL_PHOTOS:
            if k in key:
                self.artist_photo_cache[key] = LOCAL_PHOTOS[k]
                return LOCAL_PHOTOS[k]

        try:
            url = f"https://api.deezer.com/search/artist?q={urllib.parse.quote(artist)}"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("data"):
                    img = data["data"][0].get("picture_xl") or data["data"][0].get("picture_big") or data["data"][0].get("picture_medium") or ""
                    if img:
                        self.artist_photo_cache[key] = img
                        return img
        except Exception:
            pass
        return ""

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
                    artist_img = self._get_artist_photo(artist)
                    for ev in data:
                        venue = ev.get("venue", {})
                        city = venue.get("city", "").strip().lower()
                        
                        if self.target_city in city or "madrid" in city:
                            event_date_raw = ev.get("datetime", "")
                            on_sale_raw = ev.get("on_sale_datetime", "")
                            
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
                                "source": "Bandsintown",
                                "artist_image": artist_img
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
                artist_img = self._get_artist_photo(artist)
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
                        "source": "Ticketmaster",
                        "artist_image": artist_img
                    })
        except Exception as e:
            logger.debug(f"Error consultando Ticketmaster para {artist}: {e}")
            
        return events

    def search_concerts(self) -> dict:
        qualified_artists = self.load_qualified_artists()
        logger.info(f"Buscando conciertos en Madrid para {len(qualified_artists)} artistas cualificados...")

        existing_concerts = {}
        if self.concerts_file.exists():
            try:
                with open(self.concerts_file, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                    for c in old_data.get("concerts", []):
                        existing_concerts[c["id"]] = c
            except Exception:
                pass

        newly_found = {}
        for artist in qualified_artists:
            artist_events = self._query_bandsintown(artist)
            if not artist_events:
                artist_events = self._query_ticketmaster(artist)

            for ev in artist_events:
                cid = ev["id"]
                newly_found[cid] = ev

        # Preservar TODOS los conciertos existentes y fusionar descubrimientos
        merged_concerts_dict = dict(existing_concerts)
        for cid, ev in newly_found.items():
            if cid in merged_concerts_dict:
                old_c = merged_concerts_dict[cid]
                ev["status"] = old_c.get("status", ev["status"])
                ev["notified"] = old_c.get("notified", False)
                if "ticket_pdf" in old_c:
                    ev["ticket_pdf"] = old_c["ticket_pdf"]
                if "ticket_pdf_path" in old_c:
                    ev["ticket_pdf_path"] = old_c["ticket_pdf_path"]
            merged_concerts_dict[cid] = ev

        all_concerts = list(merged_concerts_dict.values())
        all_concerts.sort(key=lambda c: c.get("event_date") or "9999-12-31")

        pending_count = sum(1 for c in all_concerts if c["status"] == "PENDIENTE_VENTA")
        on_sale_count = sum(1 for c in all_concerts if c["status"] in ("ENTRADAS_A_LA_VENTA", "INTERESADO"))
        bought_count = sum(1 for c in all_concerts if c["status"] == "COMPRADO")

        result = {
            "last_updated": datetime.now().isoformat(),
            "total_concerts_found": len(all_concerts),
            "pending_sale_count": pending_count,
            "on_sale_count": on_sale_count,
            "bought_count": bought_count,
            "concerts": all_concerts
        }

        with open(self.concerts_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Búsqueda finalizada. {len(all_concerts)} conciertos retenidos y actualizados.")
        return result

if __name__ == "__main__":
    finder = ConcertFinder()
    res = finder.search_concerts()
    print(f"Búsqueda finalizada: {res['total_concerts_found']} conciertos encontrados.")
