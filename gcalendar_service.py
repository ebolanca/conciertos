import os
import json
import logging
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta
import yaml

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_CAL_AVAILABLE = True
except ImportError:
    GOOGLE_CAL_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/drive.file'
]

VENUE_ADDRESSES = {
    "sala la riviera": "Sala La Riviera, P.º Bajo de la Virgen del Puerto, S/N, Arganzuela, 28005 Madrid, España",
    "la riviera": "Sala La Riviera, P.º Bajo de la Virgen del Puerto, S/N, Arganzuela, 28005 Madrid, España",
    "movistar arena": "Movistar Arena, Av. Felipe II, s/n, Salamanca, 28009 Madrid, España",
    "wizink center": "Movistar Arena, Av. Felipe II, s/n, Salamanca, 28009 Madrid, España",
    "palacio de los deportes": "Movistar Arena, Av. Felipe II, s/n, Salamanca, 28009 Madrid, España",
    "plaza de toros de las ventas": "Plaza de Toros de Las Ventas, C. de Alcalá, 237, Salamanca, 28028 Madrid, España",
    "las ventas": "Plaza de Toros de Las Ventas, C. de Alcalá, 237, Salamanca, 28028 Madrid, España",
    "estadio santiago bernabéu": "Estadio Santiago Bernabéu, Av. de Concha Espina, 1, Chamartín, 28036 Madrid, España",
    "santiago bernabéu": "Estadio Santiago Bernabéu, Av. de Concha Espina, 1, Chamartín, 28036 Madrid, España",
    "cívitas metropolitano": "Estadio Cívitas Metropolitano, Av. de Luis Aragonés, 4, San Blas-Canillejas, 28022 Madrid, España",
    "estadio metropolitano": "Estadio Cívitas Metropolitano, Av. de Luis Aragonés, 4, San Blas-Canillejas, 28022 Madrid, España"
}

class GoogleCalendarService:
    def __init__(self, config_path="config.yaml"):
        if not Path(config_path).exists() and Path("/app/config.yaml").exists():
            config_path = "/app/config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.enabled = self.config.get("google_calendar", {}).get("enabled", True)
        self.calendar_id = self.config.get("google_calendar", {}).get("calendar_id", "primary")
        self.timezone = self.config.get("google_calendar", {}).get("timezone", "Europe/Madrid")
        
        self.credentials_file = Path("credentials.json")
        self.token_file = Path("token.json")
        self.creds = None
        self.service = None
        self.drive_service = None

    def get_calendar_link(self, title: str, start_iso: str, duration_hours: int = 1, details: str = "", location: str = "") -> str:
        try:
            if "T" in start_iso:
                dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(start_iso[:10], "%Y-%m-%d")
                dt = datetime(dt.year, dt.month, dt.day, 20, 0, 0)
        except Exception:
            dt = datetime.now() + timedelta(days=1)
        
        dt_end = dt + timedelta(hours=duration_hours)
        fmt = "%Y%m%dT%H%M%SZ"
        dates_str = f"{dt.strftime(fmt)}/{dt_end.strftime(fmt)}"
        
        params = {
            "action": "TEMPLATE",
            "text": title,
            "dates": dates_str,
            "details": details,
            "location": location
        }
        return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)

    def _get_service(self):
        if not GOOGLE_CAL_AVAILABLE or not self.enabled:
            return None
        
        if self.service:
            return self.service

        if self.token_file.exists():
            try:
                self.creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
            except Exception as e:
                logger.warning(f"No se pudo cargar token.json: {e}")

        if self.creds and self.creds.valid:
            try:
                self.service = build('calendar', 'v3', credentials=self.creds)
                self.drive_service = build('drive', 'v3', credentials=self.creds)
                return self.service
            except Exception as e:
                logger.error(f"Error creando cliente de Google Calendar: {e}")
        
        return None

    def get_full_venue_address(self, venue_raw: str) -> str:
        if not venue_raw:
            return "Madrid, España"
        venue_lower = venue_raw.strip().lower()
        for key, addr in VENUE_ADDRESSES.items():
            if key in venue_lower:
                return addr
        return f"{venue_raw}, Madrid, España"

    def parse_event_start_end(self, date_str: str):
        try:
            if "T" in date_str:
                dt_start = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                dt_base = datetime.strptime(date_str[:10], "%Y-%m-%d")
                dt_start = datetime(dt_base.year, dt_base.month, dt_base.day, 21, 0, 0)
            
            dt_end = dt_start + timedelta(hours=1)
            return dt_start.strftime("%Y-%m-%dT%H:%M:%S"), dt_end.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            now = datetime.now()
            start_default = datetime(now.year, now.month, now.day, 21, 0, 0)
            end_default = start_default + timedelta(hours=1)
            return start_default.strftime("%Y-%m-%dT%H:%M:%S"), end_default.strftime("%Y-%m-%dT%H:%M:%S")

    def add_ticket_sale_event(self, concert: dict) -> bool:
        service = self._get_service()
        sale_date_iso, end_sale_iso = self.parse_event_start_end(concert.get("ticket_sale_date", concert.get("event_date", "")))
        summary = f"🎟️ [SALIDA ENTRADAS] {concert['artist']} - Madrid"
        description = (
            f"¡Hoy salen a la venta las entradas para {concert['artist']}!
"
            f"Lugar: {concert.get('venue', 'Madrid')}
"
            f"Fecha del concierto: {concert.get('event_date', '')}
"
            f"Comprar entradas: {concert.get('ticket_url', '')}"
        )
        
        event_body = {
            'summary': summary,
            'location': self.get_full_venue_address(concert.get("venue", "")),
            'description': description,
            'start': {'dateTime': sale_date_iso, 'timeZone': self.timezone},
            'end': {'dateTime': end_sale_iso, 'timeZone': self.timezone},
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 1440},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }

        if service:
            try:
                created = service.events().insert(calendarId=self.calendar_id, body=event_body).execute()
                logger.info(f"Evento de salida a la venta creado en Google Calendar: {summary}")
                return True
            except Exception as e:
                logger.error(f"Error añadiendo evento de venta a Google Calendar: {e}")

        # Always return calendar direct link as fallback!
        cal_url = self.get_calendar_link(summary, sale_date_iso, 1, description, concert.get("venue", "Madrid"))
        concert["gcal_link"] = cal_url
        return True

    def add_concert_day_event(self, concert: dict, pdf_path: str = None) -> bool:
        service = self._get_service()
        artist_name = concert.get("artist", "Artista")
        summary = f"Concierto {artist_name}"
        start_iso, end_iso = self.parse_event_start_end(concert.get("event_date", ""))
        full_address = self.get_full_venue_address(concert.get("venue", ""))
        
        description_lines = [
            f"Concierto de {artist_name}",
            f"Lugar: {concert.get('venue', 'Madrid')}",
            f"Fecha y Hora: {start_iso.replace('T', ' ')}",
            f"Estado: Entradas Compradas 🎟️"
        ]

        event_body = {
            'summary': summary,
            'location': full_address,
            'description': "
".join(description_lines),
            'start': {'dateTime': start_iso, 'timeZone': self.timezone},
            'end': {'dateTime': end_iso, 'timeZone': self.timezone},
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 4320},
                    {'method': 'popup', 'minutes': 1440},
                    {'method': 'popup', 'minutes': 180},
                ],
            },
        }

        if service:
            try:
                created = service.events().insert(calendarId=self.calendar_id, body=event_body).execute()
                logger.info(f"Evento de concierto en Google Calendar creado exitosamente: {summary}")
                return True
            except Exception as e:
                logger.error(f"Error creando evento en Google Calendar: {e}")

        cal_url = self.get_calendar_link(summary, start_iso, 3, "
".join(description_lines), full_address)
        concert["gcal_link"] = cal_url
        return True
