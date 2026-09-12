from datetime import datetime
import requests
import json
import logging
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
import yaml

from artist_scanner import ArtistScanner
from concert_finder import ConcertFinder
from gcalendar_service import GoogleCalendarService
# WhatsAppService incrustado directamente para soporte 100% garantizado en Docker
APP_URL = "http://100.95.217.45:8086"

class WhatsAppService:
    def __init__(self, config_path="config.yaml"):
        if not Path(config_path).exists() and Path("/app/config.yaml").exists():
            config_path = "/app/config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        wa_cfg = self.config.get("whatsapp", {})
        self.enabled = wa_cfg.get("enabled", True)
        self.provider = wa_cfg.get("provider", "meta")
        self.meta_phone_number_id = wa_cfg.get("meta_phone_number_id", "1327474480443417")
        self.meta_access_token = wa_cfg.get("meta_access_token", "")
        self.meta_api_version = wa_cfg.get("meta_api_version", "v20.0")
        
        phone_raw = str(wa_cfg.get("recipient_number") or wa_cfg.get("phone_number") or "34622609030").strip()
        self.phone_number = self._format_phone(phone_raw)

    def _format_phone(self, phone: str) -> str:
        if not phone:
            return "34622609030"
        cleaned = "".join(c for c in phone if c.isdigit())
        if cleaned.startswith("00"):
            cleaned = cleaned[2:]
        if len(cleaned) == 9 and cleaned[0] in "6789":
            cleaned = "34" + cleaned
        return cleaned

    def _log_sent_message(self, message: str, phone: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        clean_msg = message.replace("\n", " ")
        log_line = f"[{timestamp}] 📤 Mensaje enviado a +{phone}: {clean_msg}"
        
        log_paths = [
            Path("data/whatsapp_sent_messages.log"),
            Path("/app/data/whatsapp_sent_messages.log"),
            Path("D:/03_Trabajo/conciertos/data/whatsapp_sent_messages.log"),
            Path.home() / ".pm2" / "logs" / "whatsapp-bot-conciertos-out.log"
        ]
        for p in log_paths:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(log_line + "\n")
            except Exception:
                pass

    def _send(self, message: str) -> bool:
        if not self.enabled:
            logger.warning("WhatsApp no está habilitado en config.yaml.")
            return False
        
        res = False
        if self.provider == "meta" and self.meta_access_token and self.meta_phone_number_id:
            # Enviar prioritariamente con la plantilla oficial aprobada 'concierto_aviso'
            # para garantizar entrega instantánea 24/7 sin importar la ventana de atención
            res = self._send_meta_template("concierto_aviso", message)
            if not res:
                # Fallback a texto plano si falla la plantilla
                res = self._send_meta_text(message)
        else:
            res = self._send_http_gateway(message)
        
        if res:
            self._log_sent_message(message, self.phone_number)
        return res

    def _send_meta_text(self, message: str) -> bool:
        url = f"https://graph.facebook.com/{self.meta_api_version}/{self.meta_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.meta_access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.phone_number,
            "type": "text",
            "text": { "preview_url": True, "body": message }
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                logger.info(f"✓ Texto Meta entregado a +{self.phone_number}")
                return True
            else:
                logger.error(f"Error texto Meta: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Excepción Meta Text API: {e}")
        return False

    def _send_meta_template(self, template_name: str, message_param: str) -> bool:
        url = f"https://graph.facebook.com/{self.meta_api_version}/{self.meta_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.meta_access_token}",
            "Content-Type": "application/json"
        }
        # Limpiar saltos de línea para el parámetro {{1}} de la plantilla oficial de Meta
        param_clean = message_param.replace("\r\n", " | ").replace("\n", " | ").strip()
        if len(param_clean) > 950:
            param_clean = param_clean[:947] + "..."
            
        payload = {
            "messaging_product": "whatsapp",
            "to": self.phone_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": { "code": "es" if template_name == "concierto_aviso" else "en_US" }
            }
        }
        if template_name == "concierto_aviso":
            payload["template"]["components"] = [
                {
                    "type": "body",
                    "parameters": [{ "type": "text", "text": param_clean }]
                }
            ]
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                logger.info(f"✓ Plantilla Meta '{template_name}' entregada con éxito a +{self.phone_number}")
                return True
            else:
                logger.error(f"Error plantilla Meta '{template_name}': {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Excepción Meta Template API: {e}")
            return False

    def _send_http_gateway(self, message: str) -> bool:
        api_url = self.config.get("whatsapp", {}).get("api_url", "http://100.95.217.45:8080/send-message")
        payload = { "number": self.phone_number, "message": message }
        try:
            resp = requests.post(api_url, json=payload, timeout=8)
            return resp.status_code in (200, 201, 202)
        except Exception:
            return False

    def send_announcement_notification(self, concert: dict) -> bool:
        artist = concert.get("artist", "Artista")
        venue = concert.get("venue", "Madrid")
        date_fmt = concert.get("event_date", "Por determinar").replace("T", " ")
        sale_fmt = concert.get("ticket_sale_date", "Por determinar").replace("T", " ")
        msg = f"Nuevo concierto anunciado de {artist} en {venue} ({date_fmt}). Salida a la venta: {sale_fmt}."
        return self._send(msg)

    def send_announcements_batch(self, concerts: list) -> bool:
        if not concerts:
            return False
        if len(concerts) == 1:
            return self.send_announcement_notification(concerts[0])

        artist = concerts[0].get("artist", "Artista")

        def get_dt_key(c):
            return str(c.get("event_date", "")).replace("T", " ")

        sorted_concerts = sorted(concerts, key=get_dt_key)

        venues = list(dict.fromkeys(c.get("venue", "Madrid") for c in sorted_concerts if c.get("venue")))
        venue_str = " / ".join(venues) if venues else "Madrid"

        dates = [c.get("event_date", "Por determinar").replace("T", " ") for c in sorted_concerts]
        if len(dates) == 2:
            dates_str = f"{dates[0]} y {dates[1]}"
        else:
            dates_str = ", ".join(dates[:-1]) + f" y {dates[-1]}"

        sales = list(dict.fromkeys(c.get("ticket_sale_date", "Por determinar").replace("T", " ") for c in sorted_concerts if c.get("ticket_sale_date")))
        sale_fmt = ", ".join(sales) if sales else "Por determinar"

        msg = f"Nuevos conciertos anunciados de {artist} en {venue_str} ({dates_str}). Salida a la venta: {sale_fmt}."
        return self._send(msg)

    def send_interested_sale_reminder(self, concert: dict) -> bool:
        artist = concert.get("artist", "Artista")
        venue = concert.get("venue", "Madrid")
        sale_fmt = concert.get("ticket_sale_date", "Por determinar").replace("T", " ")
        msg = f"Salida a la venta preparada para {artist} en {venue}. Salida: {sale_fmt}."
        return self._send(msg)

    def send_bought_concert_reminder(self, concert: dict) -> bool:
        artist = concert.get("artist", "Artista")
        venue = concert.get("venue", "Madrid")
        date_fmt = concert.get("event_date", "Por determinar").replace("T", " ")
        msg = f"Recordatorio: Concierto de {artist} en {venue} el {date_fmt}. ¡Entrada lista en la app!"
        return self._send(msg)

    def send_notification(self, concert: dict) -> bool:
        return self.send_announcement_notification(concert)

    def send_test_message(self) -> bool:
        msg = "Mensaje de prueba verificado con éxito desde Madrid Concert Notifier"
        return self._send(msg)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def parse_event_datetime(date_str: str):
    if not date_str:
        return None
    date_str = str(date_str).strip()
    if "/" in date_str:
        try:
            parts = date_str.split(" ")[0].split("/")
            if len(parts) == 3:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                h, mi, s = 0, 0, 0
                if " " in date_str:
                    time_parts = date_str.split(" ")[1].split(":")
                    h = int(time_parts[0]) if len(time_parts) > 0 else 0
                    mi = int(time_parts[1]) if len(time_parts) > 1 else 0
                    s = int(time_parts[2]) if len(time_parts) > 2 else 0
                return datetime(y, m, d, h, mi, s)
        except Exception:
            pass
    try:
        clean_iso = date_str.replace("Z", "").split("+")[0]
        return datetime.fromisoformat(clean_iso)
    except Exception:
        pass
    return None

app = FastAPI(title="Madrid Concert Notifier")

templates = Jinja2Templates(directory="templates")

tickets_dir = Path("data/tickets")
tickets_dir.mkdir(parents=True, exist_ok=True)
app.mount("/tickets", StaticFiles(directory="data/tickets"), name="tickets")

artist_images_dir = Path("data/artists_images")
artist_images_dir.mkdir(parents=True, exist_ok=True)
app.mount("/artist_images", StaticFiles(directory="data/artists_images"), name="artist_images")

scanner = ArtistScanner()
finder = ConcertFinder()
gcal = GoogleCalendarService()
whatsapp = WhatsAppService()

scheduler = BackgroundScheduler()

class ConcertActionRequest(BaseModel):
    concert_id: str

def run_full_scan_task():
    logger.info("--- Ejecutando tarea programada: Escaneo de biblioteca y búsqueda de conciertos ---")
    scanner_result = scanner.scan()
    concert_result = finder.search_concerts()
    
    concerts = concert_result.get("concerts", [])
    today_now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Agrupar conciertos pendientes de notificación por artista
    pending_by_artist = {}
    for concert in concerts:
        c_dt = parse_event_datetime(concert.get("event_date"))
        if c_dt and c_dt < today_now:
            continue
        if concert.get("status") in ("PENDIENTE_VENTA", "ENTRADAS_A_LA_VENTA") and not concert.get("notified"):
            artist_key = (concert.get("artist") or "Desconocido").strip().lower()
            pending_by_artist.setdefault(artist_key, []).append(concert)

    for artist_key, c_list in pending_by_artist.items():
        sent = whatsapp.send_announcements_batch(c_list)
        if sent:
            for c in c_list:
                c["notified"] = True
            logger.info(f"Aviso WhatsApp enviado correctamente para {c_list[0].get('artist')} ({len(c_list)} fecha(s))")
        else:
            logger.warning(f"No se pudo enviar WhatsApp para {c_list[0].get('artist')}, reintentara en proximo escaneo.")

    with open("data/concerts.json", "w", encoding="utf-8") as f:
        json.dump(concert_result, f, ensure_ascii=False, indent=2)

@app.on_event("startup")
def startup_event():
    scheduler.add_job(run_full_scan_task, "interval", hours=24, id="daily_concert_scan")
    scheduler.start()
    logger.info("Planificador iniciado: Búsqueda diaria de conciertos activa.")

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/stats")
def get_stats(include_past: bool = False):
    artists_data = {}
    if Path("data/artists.json").exists():
        with open("data/artists.json", "r", encoding="utf-8") as f:
            artists_data = json.load(f)

    concerts_data = {}
    if Path("data/concerts.json").exists():
        with open("data/concerts.json", "r", encoding="utf-8") as f:
            concerts_data = json.load(f)

    raw_concerts = concerts_data.get("concerts", [])
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    active_concerts = []
    past_concerts = []

    for c in raw_concerts:
        dt = parse_event_datetime(c.get("event_date"))
        if dt:
            c["event_date"] = dt.isoformat()
            if dt < today_start:
                c["is_past"] = True
                past_concerts.append(c)
            else:
                c["is_past"] = False
                active_concerts.append(c)
        else:
            c["is_past"] = False
            active_concerts.append(c)

    # Ordenar activos cronológicamente (los más próximos primero)
    active_concerts.sort(key=lambda c: parse_event_datetime(c.get("event_date")) or datetime.max)
    # Ordenar pasados inversamente (los más recientes primero)
    past_concerts.sort(key=lambda c: parse_event_datetime(c.get("event_date")) or datetime.min, reverse=True)

    displayed_concerts = (active_concerts + past_concerts) if include_past else active_concerts

    return {
        "total_files_scanned": artists_data.get("total_files_scanned", 0),
        "qualified_artists_count": artists_data.get("qualified_artists_count", 0),
        "qualified_artists": artists_data.get("qualified_artists", {}),
        "total_concerts_found": len(active_concerts),
        "pending_sale_count": sum(1 for c in active_concerts if c.get("status") == "PENDIENTE_VENTA"),
        "on_sale_count": sum(1 for c in active_concerts if c.get("status") in ("ENTRADAS_A_LA_VENTA", "INTERESADO")),
        "bought_count": sum(1 for c in active_concerts if c.get("status") == "COMPRADO"),
        "past_count": len(past_concerts),
        "concerts": displayed_concerts,
        "past_concerts": past_concerts
    }

@app.post("/api/scan")
def trigger_scan():
    run_full_scan_task()
    return {"status": "ok", "message": "Escaneo y búsqueda de conciertos en Madrid completados."}

@app.post("/api/test_whatsapp")
def test_whatsapp_endpoint():
    res = whatsapp.send_test_message()
    if res:
        return {"status": "ok", "message": "✅ Mensaje de prueba enviado con éxito a tu número de WhatsApp."}
    else:
        return {"status": "error", "message": "⚠️ No se pudo enviar el mensaje a WhatsApp. Revisa que el servicio de API de WhatsApp esté escuchando en la URL configurada en config.yaml."}

@app.post("/api/express_interest")
def express_interest(req: ConcertActionRequest):
    concerts_file = Path("data/concerts.json")
    if not concerts_file.exists():
        return {"status": "error", "message": "No hay conciertos registrados"}

    with open(concerts_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_concert = None
    for c in data.get("concerts", []):
        if c["id"] == req.concert_id:
            c["status"] = "INTERESADO"
            target_concert = c
            break

    if target_concert:
        gcal.add_ticket_sale_event(target_concert)
        whatsapp.send_interested_sale_reminder(target_concert)

        with open(concerts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return {"status": "ok", "message": f"Registrado interés en {target_concert['artist']}. Se ha añadido la alarma de salida a la venta a tu Google Calendar y WhatsApp."}

    return {"status": "error", "message": "Concierto no encontrado."}

@app.post("/api/cancel_interest")
def cancel_interest(req: ConcertActionRequest):
    concerts_file = Path("data/concerts.json")
    if not concerts_file.exists():
        return {"status": "error", "message": "No hay conciertos registrados"}

    with open(concerts_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_concert = None
    for c in data.get("concerts", []):
        if c["id"] == req.concert_id:
            c["status"] = "ENTRADAS_A_LA_VENTA"
            target_concert = c
            break

    if target_concert:
        with open(concerts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return {"status": "ok", "message": f"Se ha cancelado el interés en {target_concert['artist']}."}

    return {"status": "error", "message": "Concierto no encontrado."}

@app.post("/api/buy_ticket")
def buy_ticket(req: ConcertActionRequest):
    concerts_file = Path("data/concerts.json")
    if not concerts_file.exists():
        return {"status": "error", "message": "No hay conciertos registrados"}

    with open(concerts_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_concert = None
    for c in data.get("concerts", []):
        if c["id"] == req.concert_id:
            c["status"] = "COMPRADO"
            target_concert = c
            break

    if target_concert:
        pdf_path = target_concert.get("ticket_pdf_path")
        gcal.add_concert_day_event(target_concert, pdf_path=pdf_path)
        whatsapp.send_bought_concert_reminder(target_concert)

        with open(concerts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return {"status": "ok", "message": f"Concierto de {target_concert['artist']} marcado como COMPRADO y añadido a tu calendario."}

    return {"status": "error", "message": "Concierto no encontrado."}

@app.post("/api/upload_ticket")
async def upload_ticket(concert_id: str = Form(...), file: UploadFile = File(...)):
    tickets_dir = Path("data/tickets")
    tickets_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{concert_id}_{file.filename}"
    file_path = tickets_dir / filename
    
    content = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(content)
        
    pdf_url = f"/tickets/{filename}"
    
    concerts_file = Path("data/concerts.json")
    if concerts_file.exists():
        with open(concerts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        target = None
        for c in data.get("concerts", []):
            if c["id"] == concert_id:
                c["status"] = "COMPRADO"
                c["ticket_pdf"] = pdf_url
                c["ticket_pdf_path"] = str(file_path)
                target = c
                break
        
        if target:
            with open(concerts_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            gcal.add_concert_day_event(target, pdf_path=str(file_path))
            whatsapp.send_bought_concert_reminder(target)
            return {"status": "ok", "message": "Entrada PDF subida correctamente y sincronizada con Google Calendar.", "pdf_url": pdf_url}
            
    return {"status": "error", "message": "Concierto no encontrado."}

@app.get("/api/start_dashboard")
def start_dashboard():
    import subprocess
    try:
        subprocess.run(["cmd.exe", "/c", "git config --global --add safe.directory *"], cwd="D:/03_Trabajo/Dashboard_Global")
        subprocess.run(["cmd.exe", "/c", "pm2 start server.js --name dashboard-global"], cwd="D:/03_Trabajo/Dashboard_Global")
        subprocess.run(["cmd.exe", "/c", "pm2 restart dashboard-global"], cwd="D:/03_Trabajo/Dashboard_Global")
        return {"status": "ok", "message": "Dashboard Global iniciado en OMEN"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8086, reload=True)
VENUE_INFO_MAP = {
    "palacio vistalegre": {
        "name": "Palacio Vistalegre",
        "metro": "Vista Alegre (Línea 5) / Oporto (Líneas 5 y 6)",
        "address": "Calle de Utebo, 1, 28025 Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=Palacio+Vistalegre+Madrid"
    },
    "la nueva cubierta de leganés": {
        "name": "La Nueva Cubierta de Leganés",
        "metro": "Casa del Reloj (MetroSur L12) / Leganés Central (Cercanías C5)",
        "address": "Calle del Maestro, 4, 28914 Leganés, Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=La+Nueva+Cubierta+Leganes"
    },
    "wizink center": {
        "name": "WiZink Center (Palacio de los Deportes)",
        "metro": "Goya (Líneas 2 y 4) / O'Donnell (Línea 6)",
        "address": "Av. Felipe II, s/n, 28009 Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=WiZink+Center+Madrid"
    },
    "movistar arena": {
        "name": "Movistar Arena (WiZink Center)",
        "metro": "Goya (Líneas 2 y 4) / O'Donnell (Línea 6)",
        "address": "Av. Felipe II, s/n, 28009 Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=WiZink+Center+Madrid"
    },
    "estadio santiago bernabéu": {
        "name": "Estadio Santiago Bernabéu",
        "metro": "Santiago Bernabéu (Línea 10)",
        "address": "Av. de Concha Espina, 1, 28036 Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=Estadio+Santiago+Bernabeu+Madrid"
    },
    "estadio bernabéu": {
        "name": "Estadio Santiago Bernabéu",
        "metro": "Santiago Bernabéu (Línea 10)",
        "address": "Av. de Concha Espina, 1, 28036 Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=Estadio+Santiago+Bernabeu+Madrid"
    },
    "riyadh air metropolitano": {
        "name": "Riyadh Air Metropolitano",
        "metro": "Estadio Metropolitano (Línea 7)",
        "address": "Av. de Luis Aragonés, 4, 28022 Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=Riyadh+Air+Metropolitano+Madrid"
    },
    "la riviera": {
        "name": "Sala La Riviera",
        "metro": "Puerta del Ángel (Línea 6) / Príncipe Pío (L1, L6, L10, R)",
        "address": "Paseo Bajo de la Virgen del Puerto, s/n, 28005 Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=La+Riviera+Madrid"
    },
    "teatro kapital": {
        "name": "Teatro Kapital",
        "metro": "Atocha (Línea 1) / Estación del Arte (Línea 1)",
        "address": "Calle de Atocha, 125, 28012 Madrid",
        "maps_url": "https://www.google.com/maps/dir/?api=1&destination=Teatro+Kapital+Madrid"
    }
}

ARTIST_SETLISTS = {
    "evanescence": [
        "1. Bring Me to Life", "2. Going Under", "3. Call Me When You're Sober",
        "4. Lithium", "5. My Immortal", "6. What You Want", "7. Imaginary",
        "8. Better Without You", "9. Wasted on You", "10. End of the Dream"
    ],
    "binomio de oro de américa": [
        "1. Me Ilusioné", "2. Niña Bonita", "3. Quiero Que Seas Mi Estrella",
        "4. Si Tu Amor No Vuelve", "5. Cómo Expresar Lo Que Siento", "6. Olvídala",
        "7. Un Osito Dormilón", "8. Amigo", "9. Distintos Destinos", "10. Inmortal"
    ],
    "amaral": [
        "1. El universo sobre mí", "2. Cómo hablar", "3. Días de verano",
        "4. Marta, Sebas, Guille y los demás", "5. Kamikaze", "6. Sin ti no soy nada",
        "7. Toda la noche en la calle", "8. Moriría por vos", "9. Hacia lo salvaje"
    ],
    "alex ubago": [
        "1. Sin miedo a nada", "2. A gritos de esperanza", "3. Aunque no te pueda ver",
        "4. ¿Qué pides tú?", "5. Me arrepiento", "6. Ella vive en mí", "7. Estar contigo"
    ],
    "morat": [
        "1. Besos en guerra", "2. Cómo te atreves", "3. No se va", "4. Cuando nadie ve",
        "5. Salir con vida", "6. Por fa no te vayas", "7. 506", "8. París"
    ],
    "aitana": [
        "1. Las Babys", "2. Los Ángeles", "3. Vas a quedarte", "4. Mon Amour (Remix)",
        "5. Formentera", "6. Mi Amor", "7. En El Coche", "8. 11 Razones"
    ],
    "the weeknd": [
        "1. Blinding Lights", "2. Starboy", "3. The Hills", "4. Save Your Tears",
        "5. Die For You", "6. Can't Feel My Face", "7. I Feel It Coming", "8. Creepin'"
    ],
    "shakira": [
        "1. Hips Don't Lie", "2. Session 53 (BZRP)", "3. Te Felicito", "4. Monotonía",
        "5. Waka Waka (This Time for Africa)", "6. Whenever, Wherever", "7. Inevitable"
    ],
    "pitbull": [
        "1. Give Me Everything", "2. Timber", "3. Hotel Room Service", "4. Time of Our Lives",
        "5. Fireball", "6. International Love", "7. Rain Over Me"
    ],
    "bryan adams": [
        "1. Summer of '69", "2. (Everything I Do) I Do It for You", "3. Heaven",
        "4. Run to You", "5. Please Forgive Me", "6. Cuts Like a Knife"
    ]
}

@app.get("/api/venue_info/{venue_name}")
def get_venue_info(venue_name: str):
    key = venue_name.strip().lower()
    for v_key, info in VENUE_INFO_MAP.items():
        if v_key in key or key in v_key:
            return {"status": "ok", "venue": info}
    encoded = urllib.parse.quote(venue_name + " Madrid")
    return {
        "status": "ok",
        "venue": {
            "name": venue_name,
            "metro": "Transporte Público Madrid",
            "address": f"{venue_name}, Madrid",
            "maps_url": f"https://www.google.com/maps/dir/?api=1&destination={encoded}"
        }
    }

@app.get("/api/setlist/{artist_name}")
def get_artist_setlist(artist_name: str):
    key = artist_name.strip().lower()
    for a_key, songs in ARTIST_SETLISTS.items():
        if a_key in key or key in a_key:
            return {"status": "ok", "artist": artist_name, "songs": songs}
    
    # Generic setlist fallback
    fallback_songs = [
        f"1. Éxito Principal - {artist_name}",
        f"2. Gran Canción Gira 2026 - {artist_name}",
        f"3. Tema Favorito Fans - {artist_name}",
        f"4. Tema Acústico - {artist_name}",
        f"5. Cierre de Concierto - {artist_name}"
    ]
    return {"status": "ok", "artist": artist_name, "songs": fallback_songs}

