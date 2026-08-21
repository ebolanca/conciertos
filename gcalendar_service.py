import os
import json
import logging
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
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.enabled = self.config["google_calendar"].get("enabled", True)
        self.calendar_id = self.config["google_calendar"].get("calendar_id", "primary")
        self.timezone = self.config["google_calendar"].get("timezone", "Europe/Madrid")
        
        self.credentials_file = Path("credentials.json")
        self.token_file = Path("token.json")
        self.creds = None
        self.service = None
        self.drive_service = None

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

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Error refrescando credenciales de Google: {e}")
                    self.creds = None
            
            if not self.creds and self.credentials_file.exists():
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
                    self.creds = flow.run_local_server(port=0)
                    with open(self.token_file, "w", encoding="utf-8") as token:
                        token.write(self.creds.to_json())
                except Exception as e:
                    logger.warning(f"No se completó la autenticación interactiva de Google: {e}")
                    return None

        if self.creds:
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

    def upload_pdf_to_drive(self, pdf_path: str, filename: str) -> str:
        try:
            if not self._get_service() or not self.drive_service:
                return None
            
            file_metadata = {
                'name': filename,
                'mimeType': 'application/pdf'
            }
            media = MediaFileUpload(pdf_path, mimetype='application/pdf')
            drive_file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink, webContentLink'
            ).execute()
            
            file_id = drive_file.get('id')
            try:
                self.drive_service.permissions().create(
                    fileId=file_id,
                    body={'type': 'anyone', 'role': 'reader'}
                ).execute()
            except Exception as pe:
                logger.warning(f"No se pudo cambiar permiso público del archivo Drive: {pe}")

            link = drive_file.get('webViewLink') or drive_file.get('webContentLink')
            logger.info(f"PDF subido correctamente a Google Drive: {link}")
            return link
        except Exception as e:
            logger.error(f"Error subiendo entrada PDF a Google Drive: {e}")
            return None

    def add_ticket_sale_event(self, concert: dict) -> bool:
        service = self._get_service()
        sale_date_iso, end_sale_iso = self.parse_event_start_end(concert.get("ticket_sale_date", concert.get("event_date", "")))
        
        summary = f"🎟️ [SALIDA ENTRADAS] {concert['artist']} - Madrid"
        description = (
            f"¡Hoy salen a la venta las entradas para {concert['artist']}!\n"
            f"Lugar: {concert.get('venue', 'Madrid')}\n"
            f"Fecha del concierto: {concert.get('event_date', '')}\n"
            f"Comprar entradas: {concert.get('ticket_url', '')}"
        )
        
        event_body = {
            'summary': summary,
            'location': self.get_full_venue_address(concert.get("venue", "")),
            'description': description,
            'start': {
                'dateTime': sale_date_iso,
                'timeZone': self.timezone,
            },
            'end': {
                'dateTime': end_sale_iso,
                'timeZone': self.timezone,
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 1440}, # 1 día antes
                    {'method': 'popup', 'minutes': 10},   # 10 minutos antes
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

        return False

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
        
        attachments = []
        if pdf_path and os.path.exists(pdf_path):
            filename = f"Entradas {artist_name}.pdf"
            drive_url = self.upload_pdf_to_drive(pdf_path, filename)
            if drive_url:
                attachments.append({
                    'fileUrl': drive_url,
                    'title': filename,
                    'mimeType': 'application/pdf'
                })
                description_lines.append(f"Adjunto Entrada PDF: {drive_url}")

        event_body = {
            'summary': summary,
            'location': full_address,
            'description': "\n".join(description_lines),
            'start': {
                'dateTime': start_iso,
                'timeZone': self.timezone,
            },
            'end': {
                'dateTime': end_iso,
                'timeZone': self.timezone,
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 4320},  # 3 días antes
                    {'method': 'popup', 'minutes': 1440},  # 1 día antes
                    {'method': 'popup', 'minutes': 180},   # 3 horas antes
                ],
            },
        }

        if attachments:
            event_body['attachments'] = attachments

        if service:
            try:
                created = service.events().insert(
                    calendarId=self.calendar_id,
                    body=event_body,
                    supportsAttachments=True
                ).execute()
                logger.info(f"Evento de concierto en Google Calendar creado exitosamente: {summary}")
                return True
            except Exception as e:
                logger.error(f"Error creando evento en Google Calendar: {e}")

        return False
