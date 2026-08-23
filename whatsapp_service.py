import logging
from pathlib import Path
from datetime import datetime
import yaml
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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
            res = self._send_meta_template("concierto_aviso", message)
            if not res:
                res = self._send_meta_template("hello_world", message)
        else:
            res = self._send_http_gateway(message)
        
        if res:
            self._log_sent_message(message, self.phone_number)
        return res

    def _send_meta_template(self, template_name: str, message_param: str) -> bool:
        url = f"https://graph.facebook.com/{self.meta_api_version}/{self.meta_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.meta_access_token}",
            "Content-Type": "application/json"
        }
        
        # Clean message parameter for Meta template (max 1024 chars, no newlines inside variable)
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
            logger.info(f"Enviando Plantilla Meta '{template_name}' a +{self.phone_number}...")
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                logger.info(f"✓ Plantilla Meta entregada con éxito a +{self.phone_number}")
                return True
            else:
                logger.error(f"Error Meta Cloud API (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Excepción conectando con Meta Cloud API: {e}")
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
        msg = f"📢 ¡NUEVO CONCIERTO ANUNCIADO EN MADRID! Artista: {concert.get('artist', 'Artista')} | Lugar: {concert.get('venue', 'Madrid')} | Fecha Concierto: {concert.get('event_date', 'Por determinar')} | Salida a Venta: {concert.get('ticket_sale_date', 'Por determinar')} | Enlace: {concert.get('ticket_url', '')}"
        return self._send(msg)

    def send_interested_sale_reminder(self, concert: dict) -> bool:
        msg = f"⭐ ¡INTERÉS REGISTRADO! Se ha guardado la SALIDA A LA VENTA para {concert.get('artist', 'Artista')} el {concert.get('ticket_sale_date', 'Por determinar')} en {concert.get('venue', 'Madrid')}. Avisos 1 día antes y 10 min antes. Comprar: {concert.get('ticket_url', '')}"
        return self._send(msg)

    def send_bought_concert_reminder(self, concert: dict) -> bool:
        msg = f"🎟️ ¡ENTRADA CONFIRMADA! Concierto de {concert.get('artist', 'Artista')} en {concert.get('venue', 'Madrid')} el {concert.get('event_date', 'Por determinar')}. Avisos 3 días antes, 1 día antes y 3 horas antes."
        return self._send(msg)

    def send_notification(self, concert: dict) -> bool:
        return self.send_announcement_notification(concert)

    def send_test_message(self) -> bool:
        return self._send("🧪 Mensaje de prueba desde Madrid Concert Notifier - Servicio Meta Cloud API activo 🎟️")
