import logging
from pathlib import Path
import yaml
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        wa_cfg = self.config.get("whatsapp", {})
        self.enabled = wa_cfg.get("enabled", True)
        self.api_url = wa_cfg.get("api_url", "http://100.95.217.45:3000/send-message")
        self.phone_number = wa_cfg.get("phone_number", "")

    def _send(self, message: str) -> bool:
        if not self.enabled or not self.phone_number:
            logger.warning("WhatsApp no está habilitado o falta phone_number en config.yaml.")
            return False
        
        payload = {
            "number": self.phone_number,
            "message": message
        }

        try:
            resp = requests.post(self.api_url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Mensaje de WhatsApp enviado correctamente: {message[:40]}...")
                return True
            else:
                logger.error(f"Error enviando WhatsApp (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Excepción al enviar WhatsApp: {e}")
            
        return False

    def send_announcement_notification(self, concert: dict) -> bool:
        msg = (
            f"📢 ¡NUEVO CONCIERTO ANUNCIADO EN MADRID!\n\n"
            f"🎤 Artista: {concert.get('artist', 'Artista')}\n"
            f"📍 Lugar: {concert.get('venue', 'Madrid')}\n"
            f"📅 Fecha Concierto: {concert.get('event_date', 'Por determinar')}\n"
            f"🎟️ Salida a la Venta: {concert.get('ticket_sale_date', 'Por determinar')}\n"
            f"🔗 Enlace: {concert.get('ticket_url', '')}\n\n"
            f"Entra en la app de conciertos y pulsa '⭐ Me interesa' si quieres añadir la alarma de salida a la venta a tu Google Calendar."
        )
        return self._send(msg)

    def send_interested_sale_reminder(self, concert: dict) -> bool:
        msg = (
            f"⭐ ¡INTERÉS REGISTRADO!\n\n"
            f"Se ha guardado el evento en tu Google Calendar para la SALIDA A LA VENTA de entradas:\n"
            f"🎤 Artista: {concert.get('artist', 'Artista')}\n"
            f"📍 Lugar: {concert.get('venue', 'Madrid')}\n"
            f"🎟️ Salida a la Venta: {concert.get('ticket_sale_date', 'Por determinar')}\n\n"
            f"⏰ Avisos configurados en Google Calendar y WhatsApp:\n"
            f"• 1 día antes\n"
            f"• 10 minutos antes\n"
            f"🔗 Comprar en: {concert.get('ticket_url', '')}"
        )
        return self._send(msg)

    def send_bought_concert_reminder(self, concert: dict) -> bool:
        pdf_info = "📄 Entrada PDF adjunta y disponible en la app." if concert.get('ticket_pdf') else ""
        msg = (
            f"🎟️ ¡ENTRADA CONFIRMADA Y PROCESADA!\n\n"
            f"Se ha programado el evento del DÍA DEL CONCIERTO en tu Google Calendar:\n"
            f"🎤 Artista: {concert.get('artist', 'Artista')}\n"
            f"📍 Lugar: {concert.get('venue', 'Madrid')}\n"
            f"📅 Fecha: {concert.get('event_date', 'Por determinar')}\n"
            f"{pdf_info}\n\n"
            f"⏰ Avisos configurados:\n"
            f"• 3 días antes\n"
            f"• 1 día antes\n"
            f"• 3 horas antes"
        )
        return self._send(msg)

    def send_notification(self, concert: dict) -> bool:
        return self.send_announcement_notification(concert)

    def send_test_message(self) -> bool:
        return self._send("🧪 Mensaje de prueba desde Madrid Concert Notifier - Servicio WhatsApp activo.")
