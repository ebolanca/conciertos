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

    def _send(self, message: str) -> bool:
        if not self.enabled:
            logger.warning("WhatsApp no está habilitado en config.yaml.")
            return False
        
        if self.provider == "meta" and self.meta_access_token and self.meta_phone_number_id:
            return self._send_meta(message)
        else:
            return self._send_http_gateway(message)

    def _send_meta(self, message: str) -> bool:
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
            logger.info(f"Enviando WhatsApp vía Meta Cloud API a +{self.phone_number}...")
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                logger.info(f"✓ Mensaje de WhatsApp entregado con éxito a +{self.phone_number}")
                return True
            else:
                logger.warning(f"Respuesta de Meta (Status {resp.status_code}), intentando plantilla fallback...")
                return self._send_meta_template("hello_world")
        except Exception as e:
            logger.error(f"Excepción conectando con Meta Cloud API: {e}")
        return False

    def _send_meta_template(self, template_name: str) -> bool:
        url = f"https://graph.facebook.com/{self.meta_api_version}/{self.meta_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.meta_access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": self.phone_number,
            "type": "template",
            "template": { "name": template_name, "language": { "code": "en_US" } }
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            return resp.status_code in (200, 201)
        except Exception:
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
        msg = f"📢 ¡NUEVO CONCIERTO ANUNCIADO EN MADRID!\n\n🎤 Artista: {concert.get('artist', 'Artista')}\n📍 Lugar: {concert.get('venue', 'Madrid')}\n📅 Fecha Concierto: {concert.get('event_date', 'Por determinar')}\n🎟️ Salida a la Venta: {concert.get('ticket_sale_date', 'Por determinar')}\n🔗 Enlace: {concert.get('ticket_url', '')}\n\nEntra en la app de conciertos y pulsa '⭐ Me interesa' si quieres añadir la alarma de salida a la venta a tu Google Calendar."
        return self._send(msg)

    def send_interested_sale_reminder(self, concert: dict) -> bool:
        msg = f"⭐ ¡INTERÉS REGISTRADO!\n\nSe ha guardado el evento en tu Google Calendar para la SALIDA A LA VENTA de entradas:\n🎤 Artista: {concert.get('artist', 'Artista')}\n📍 Lugar: {concert.get('venue', 'Madrid')}\n🎟️ Salida a la Venta: {concert.get('ticket_sale_date', 'Por determinar')}\n\n⏰ Avisos configurados en Google Calendar y WhatsApp:\n• 1 día antes\n• 10 minutos antes\n🔗 Comprar en: {concert.get('ticket_url', '')}"
        return self._send(msg)

    def send_bought_concert_reminder(self, concert: dict) -> bool:
        pdf_info = "📄 Entrada PDF adjunta y disponible en la app." if concert.get('ticket_pdf') else ""
        msg = f"🎟️ ¡ENTRADA CONFIRMADA Y PROCESADA!\n\nSe ha programado el evento del DÍA DEL CONCIERTO en tu Google Calendar:\n🎤 Artista: {concert.get('artist', 'Artista')}\n📍 Lugar: {concert.get('venue', 'Madrid')}\n📅 Fecha: {concert.get('event_date', 'Por determinar')}\n{pdf_info}\n\n⏰ Avisos configurados:\n• 3 días antes\n• 1 día antes\n• 3 horas antes"
        return self._send(msg)

    def send_notification(self, concert: dict) -> bool:
        return self.send_announcement_notification(concert)

    def send_test_message(self) -> bool:
        return self._send("🧪 Mensaje de prueba desde Madrid Concert Notifier - Servicio Meta Cloud API activo 🎟️")
