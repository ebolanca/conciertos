import json
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
import yaml

from artist_scanner import ArtistScanner
from concert_finder import ConcertFinder
from gcalendar_service import GoogleCalendarService
from whatsapp_service import WhatsAppService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Madrid Concert Notifier")

templates = Jinja2Templates(directory="templates")

scanner = ArtistScanner()
finder = ConcertFinder()
gcal = GoogleCalendarService()
whatsapp = WhatsAppService()

scheduler = BackgroundScheduler()

class TicketPurchaseRequest(BaseModel):
    concert_id: str

def run_full_scan_task():
    logger.info("--- Ejecutando tarea programada: Escaneo de biblioteca y búsqueda de conciertos ---")
    scanner_result = scanner.scan()
    concert_result = finder.search_concerts()
    
    # Notificar nuevos conciertos detectados por WhatsApp y Google Calendar
    concerts = concert_result.get("concerts", [])
    for concert in concerts:
        if concert.get("status") in ("PENDIENTE_VENTA", "ENTRADAS_A_LA_VENTA") and not concert.get("notified"):
            whatsapp.send_notification(concert)
            gcal.add_ticket_sale_event(concert)
            concert["notified"] = True

    # Guardar cambios
    with open("data/concerts.json", "w", encoding="utf-8") as f:
        json.dump(concert_result, f, ensure_ascii=False, indent=2)

@app.on_event("startup")
def startup_event():
    # Programar escaneo automático diario
    scheduler.add_job(run_full_scan_task, 'interval', hours=24, id="daily_concert_scan")
    scheduler.start()
    logger.info("Planificador iniciado: Búsqueda diaria de conciertos activa.")

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/stats")
def get_stats():
    artists_data = {}
    if Path("data/artists.json").exists():
        with open("data/artists.json", "r", encoding="utf-8") as f:
            artists_data = json.load(f)

    concerts_data = {}
    if Path("data/concerts.json").exists():
        with open("data/concerts.json", "r", encoding="utf-8") as f:
            concerts_data = json.load(f)

    return {
        "total_files_scanned": artists_data.get("total_files_scanned", 0),
        "qualified_artists_count": artists_data.get("qualified_artists_count", 0),
        "qualified_artists": artists_data.get("qualified_artists", {}),
        "total_concerts_found": concerts_data.get("total_concerts_found", 0),
        "pending_sale_count": concerts_data.get("pending_sale_count", 0),
        "on_sale_count": concerts_data.get("on_sale_count", 0),
        "bought_count": concerts_data.get("bought_count", 0),
        "concerts": concerts_data.get("concerts", [])
    }

@app.post("/api/scan")
def trigger_scan():
    run_full_scan_task()
    return {"status": "ok", "message": "Escaneo y búsqueda de conciertos en Madrid completados."}

@app.post("/api/test_whatsapp")
def test_whatsapp_endpoint():
    res = whatsapp.send_test_message()
    return {"status": "ok" if res else "error", "message": "Mensaje de prueba de WhatsApp procesado."}

@app.post("/api/buy_ticket")
def buy_ticket(req: TicketPurchaseRequest):
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
        # Añadir evento del día del concierto a las 9:00 AM
        gcal.add_concert_day_event(target_concert)

        with open(concerts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return {"status": "ok", "message": f"Concierto de {target_concert['artist']} marcado como COMPRADO y añadido a tu calendario."}

    return {"status": "error", "message": "Concierto no encontrado."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8085, reload=True)
