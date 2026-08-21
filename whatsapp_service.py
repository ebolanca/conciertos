import json
import logging
import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.enabled = self.config["whatsapp"].get("enabled", True)
        self.api_url = self.config["whatsapp"].get("api_url", "http://100.95.217.45:8080/send-message")
        self.sender = self.config["whatsapp"].get("sender_number", "694262385")
        self.recipient = self.config["whatsapp"].get("recipient_number", "622609030")

    def format_concert_message(self, concert: dict) -> str:
        status_emoji = "🎟️" if concert.get("status") == "ENTRADAS_A_LA_VENTA" else "⏳"
        status_text = (
            "¡ENTRADAS YA A LA VENTA!"
            if concert.get("status") == "ENTRADAS_A_LA_VENTA"
            else "Anunciado (Pendiente de salida a la venta)"
        )

        msg = (
            f"🚨 *¡CONCIERTO ANUNCIADO EN MADRID!* {status_emoji}\n\n"
            f"🎤 *Artista:* {concert['artist']}\n"
            f"📍 *Lugar:* {concert.get('venue', 'Madrid')}\n"
            f"📅 *Fecha del Concierto:* {concert.get('event_date', 'Por confirmar')}\n"
            f"🛒 *Entradas:* {status_text}\n"
            f"⏰ *Fecha Salida Entradas:* {concert.get('ticket_sale_date', 'Ya a la venta')}\n\n"
            f"🔗 *Enlace de compra:* {concert.get('ticket_url', 'No disponible')}\n\n"
            f"📅 *Nota:* He añadido una alerta en tu Google Calendar para las 09:00 AM el día de salida de entradas."
        )
        return msg

    def send_notification(self, concert: dict) -> bool:
        if not self.enabled:
            logger.info("WhatsApp desactivado en la configuración.")
            return False

        text = self.format_concert_message(concert)
        
        # Enviar petición HTTP a la API de WhatsApp del usuario
        payloads = [
            # Formato estándar Baileys / Evolution / WPPConnect / Custom Gateway
            {"number": self.recipient, "sender": self.sender, "message": text},
            {"to": f"34{self.recipient}@s.whatsapp.net", "from": self.sender, "text": text},
            {"recipient": self.recipient, "text": text}
        ]

        success = False
        for payload in payloads:
            try:
                headers = {"Content-Type": "application/json"}
                resp = requests.post(self.api_url, json=payload, headers=headers, timeout=5)
                if resp.status_code in (200, 201, 202):
                    logger.info(f"Mensaje de WhatsApp enviado correctamente a {self.recipient}")
                    success = True
                    break
            except Exception as e:
                logger.debug(f"Intento de envío de WhatsApp con payload {payload} falló: {e}")

        if not success:
            logger.warning(f"No se pudo contactar con la API de WhatsApp en {self.api_url}. Mensaje simulado en consola:\n{text}")

        return success

    def send_test_message(self) -> bool:
        test_concert = {
            "artist": "Artista de Prueba",
            "venue": "WiZink Center",
            "event_date": "2026-11-15",
            "ticket_sale_date": "2026-09-01 a las 10:00 AM",
            "ticket_url": "https://www.ticketmaster.es",
            "status": "PENDIENTE_VENTA"
        }
        return self.send_notification(test_concert)

if __name__ == "__main__":
    wa = WhatsAppService()
    wa.send_test_message()
