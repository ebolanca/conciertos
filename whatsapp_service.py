import logging
from pathlib import Path
from datetime import datetime
import yaml
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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
            # First try free-form text message so formatting with newlines is preserved perfectly
            res = self._send_meta_text(message)
            if not res:
                res = self._send_meta_template("concierto_aviso", message)
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
        except Exception as e:
            logger.error(f"Excepción Meta Text API: {e}")
        return False

    def _send_meta_template(self, template_name: str, message_param: str) -> bool:
        url = f"https://graph.facebook.com/{self.meta_api_version}/{self.meta_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.meta_access_token}",
            "Content-Type": "application/json"
        }
        param_clean = message_param.replace("\n", " • ")[:1000]
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
        date_fmt = concert.get("event_date", "Por determinar").replace("T", " ")
        sale_fmt = concert.get("ticket_sale_date", "Por determinar").replace("T", " ")
        msg = (
            f"📢 ¡NUEVO CONCIERTO ANUNCIADO EN MADRID!\n\n"
            f"🎤 Artista: {concert.get('artist', 'Artista')}\n"
            f"📍 Lugar: {concert.get('venue', 'Madrid')}\n"
            f"📅 Fecha Concierto: {date_fmt}\n"
            f"🎟️ Salida a la Venta: {sale_fmt}\n"
            f"🛒 Comprar en: {concert.get('ticket_url', '')}\n\n"
            f"📱 Abre tu app de conciertos para guardar en tu calendario:\n{APP_URL}"
        )
        return self._send(msg)

    def send_interested_sale_reminder(self, concert: dict) -> bool:
        sale_fmt = concert.get("ticket_sale_date", "Por determinar").replace("T", " ")
        msg = (
            f"⭐ ¡INTERÉS REGISTRADO!\n\n"
            f"Se ha preparado la SALIDA A LA VENTA de entradas:\n"
            f"🎤 Artista: {concert.get('artist', 'Artista')}\n"
            f"📍 Lugar: {concert.get('venue', 'Madrid')}\n"
            f"🎟️ Salida a la Venta: {sale_fmt}\n\n"
            f"⏰ Avisos programados: 1 día antes y 10 minutos antes.\n"
            f"🛒 Enlace de compra: {concert.get('ticket_url', '')}\n\n"
            f"📱 Abre tu app de conciertos:\n{APP_URL}"
        )
        return self._send(msg)

    def send_bought_concert_reminder(self, concert: dict) -> bool:
        date_fmt = concert.get("event_date", "Por determinar").replace("T", " ")
        pdf_info = "📄 Entrada PDF adjunta en tu app." if concert.get('ticket_pdf') else ""
        msg = (
            f"🎟️ ¡ENTRADA CONFIRMADA Y PROCESADA!\n\n"
            f"Cita para el DÍA DEL CONCIERTO preparada:\n"
            f"🎤 Artista: {concert.get('artist', 'Artista')}\n"
            f"📍 Lugar: {concert.get('venue', 'Madrid')}\n"
            f"📅 Fecha Concierto: {date_fmt}\n"
            f"{pdf_info}\n\n"
            f"⏰ Avisos programados: 3 días antes, 1 día antes y 3 horas antes.\n\n"
            f"📱 Abre tu app de conciertos:\n{APP_URL}"
        )
        return self._send(msg)

    def send_notification(self, concert: dict) -> bool:
        return self.send_announcement_notification(concert)

    def send_test_message(self) -> bool:
        msg = f"🧪 Mensaje de prueba desde Madrid Concert Notifier - Servicio WhatsApp activo 🎟️\n\n📱 Abre tu app de conciertos:\n{APP_URL}"
        return self._send(msg)
