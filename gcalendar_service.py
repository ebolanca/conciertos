import os
import json
import logging
from pathlib import Path
from datetime import datetime, time
import yaml

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GOOGLE_CAL_AVAILABLE = True
except ImportError:
    GOOGLE_CAL_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

class GoogleCalendarService:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.enabled = self.config["google_calendar"].get("enabled", True)
        self.calendar_id = self.config["google_calendar"].get("calendar_id", "primary")
        self.timezone = self.config["google_calendar"].get("timezone", "Europe/Madrid")
        self.alert_time_str = self.config["google_calendar"].get("alert_time", "09:00")
        
        self.credentials_file = Path("credentials.json")
        self.token_file = Path("token.json")
        self.service = None

    def _get_service(self):
        if not GOOGLE_CAL_AVAILABLE or not self.enabled:
            return None
        
        if self.service:
            return self.service

        creds = None
        if self.token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
            except Exception as e:
                logger.warning(f"No se pudo cargar token.json: {e}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Error refrescando credenciales de Google: {e}")
                    creds = None
            
            if not creds and self.credentials_file.exists():
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
                    creds = flow.run_local_server(port=0)
                    with open(self.token_file, "w", encoding="utf-8") as token:
                        token.write(creds.to_json())
                except Exception as e:
                    logger.warning(f"No se completó la autenticación interactiva de Google: {e}")
                    return None

        if creds:
            try:
                self.service = build('calendar', 'v3', credentials=creds)
                return self.service
            except Exception as e:
                logger.error(f"Error creando cliente de Google Calendar: {e}")
        
        return None

    def format_date_to_9am(self, date_str: str) -> str:
        """Convierte una cadena de fecha a formato ISO 8601 a las 09:00:00 en zona horaria Madrid."""
        try:
            if "T" in date_str:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            
            h, m = map(int, self.alert_time_str.split(":"))
            dt_9am = datetime(dt.year, dt.month, dt.day, h, m, 0)
            return dt_9am.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            return date_str

    def add_ticket_sale_event(self, concert: dict) -> bool:
        """Crea o actualiza el evento de SALIDA A LA VENTA DE ENTRADAS."""
        service = self._get_service()
        sale_date_iso = self.format_date_to_9am(concert.get("ticket_sale_date", concert.get("event_date", "")))
        
        summary = f"🎟️ [SALIDA ENTRADAS] {concert['artist']} - Madrid"
        description = (
            f"¡Entradas a la venta para {concert['artist']}!\n"
            f"Lugar: {concert.get('venue', 'Madrid')}\n"
            f"Fecha del concierto: {concert.get('event_date', '')}\n"
            f"Comprar entradas: {concert.get('ticket_url', '')}\n"
            f"Fuente: {concert.get('source', '')}"
        )
        
        event_body = {
            'summary': summary,
            'location': f"{concert.get('venue', '')}, Madrid, España",
            'description': description,
            'start': {
                'dateTime': sale_date_iso,
                'timeZone': self.timezone,
            },
            'end': {
                'dateTime': sale_date_iso,
                'timeZone': self.timezone,
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 0},  # Alarma exacta a las 9:00 AM
                    {'method': 'popup', 'minutes': 120}, # Alarma 2 horas antes
                ],
            },
        }

        if service:
            try:
                created = service.events().insert(calendarId=self.calendar_id, body=event_body).execute()
                logger.info(f"Evento de salida a la venta creado en Google Calendar: {summary}")
                return True
            except Exception as e:
                logger.error(f"Error añadiendo evento a Google Calendar: {e}")

        self.export_ics_file(concert, "ENTRADAS")
        return False

    def add_concert_day_event(self, concert: dict) -> bool:
        """Crea el evento CONFIRMADO el día del concierto."""
        service = self._get_service()
        event_date_iso = self.format_date_to_9am(concert.get("event_date", ""))
        
        summary = f"🎵 [CONCIERTO CONFIRMADO] {concert['artist']} @ {concert.get('venue', 'Madrid')}"
        description = (
            f"¡Hoy es el concierto de {concert['artist']}!\n"
            f"Lugar: {concert.get('venue', 'Madrid')}\n"
            f"Entradas compradas: Sí 🎟️\n"
            f"Info: {concert.get('ticket_url', '')}"
        )
        
        event_body = {
            'summary': summary,
            'location': f"{concert.get('venue', '')}, Madrid, España",
            'description': description,
            'start': {
                'dateTime': event_date_iso,
                'timeZone': self.timezone,
            },
            'end': {
                'dateTime': event_date_iso,
                'timeZone': self.timezone,
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 0},
                    {'method': 'popup', 'minutes': 1440}, # 1 día antes
                ],
            },
        }

        if service:
            try:
                created = service.events().insert(calendarId=self.calendar_id, body=event_body).execute()
                logger.info(f"Evento del concierto creado en Google Calendar: {summary}")
                return True
            except Exception as e:
                logger.error(f"Error añadiendo evento de concierto a Google Calendar: {e}")

        self.export_ics_file(concert, "CONCIERTO")
        return False

    def export_ics_file(self, concert: dict, event_type: str):
        """Genera/actualiza un archivo .ics local para importar en cualquier calendario."""
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)
        ics_path = data_dir / "madrid_concerts.ics"

        dt_str = concert.get("ticket_sale_date" if event_type == "ENTRADAS" else "event_date", "")
        dt_clean = dt_str.replace("-", "").replace(":", "")[:15] or datetime.now().strftime("%Y%m%dT090000")

        ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Madrid Concert Notifier//ES
BEGIN:VEVENT
SUMMARY:{'🎟️ ENTRADAS' if event_type=='ENTRADAS' else '🎵 CONCIERTO'}: {concert['artist']} en Madrid
DESCRIPTION:{concert.get('ticket_url', '')} - {concert.get('venue', '')}
LOCATION:{concert.get('venue', 'Madrid')}, Madrid, Spain
DTSTART:{dt_clean}
DTEND:{dt_clean}
END:VEVENT
END:VCALENDAR
"""
        with open(ics_path, "a", encoding="utf-8") as f:
            f.write(ics_content + "\n")
        logger.info(f"Evento guardado en archivo iCal fallback: {ics_path}")

if __name__ == "__main__":
    gcal = GoogleCalendarService()
    print("Google Calendar Service inicializado.")
