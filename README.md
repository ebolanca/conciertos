# 🎸 Madrid Concert Notifier (Dockerized)

Aplicación automatizada para escanear tu biblioteca local de música en el servidor OMEN, detectar conciertos en **Madrid** de tus artistas favoritos (con **>= 3 canciones**), enviarte alertas por **WhatsApp** y agendar automáticamente recordatorios a las **09:00 AM** en tu **Google Calendar**.

---

## 🤖 INSTRUCCIONES PARA ANTIGRAVITY / AGENTE EN OMEN

Si estás leyendo este proyecto desde **Antigravity en el servidor OMEN**:

1. **Ubicación del proyecto**: Esta carpeta contiene todos los archivos fuente (`main.py`, `artist_scanner.py`, `concert_finder.py`, `gcalendar_service.py`, `whatsapp_service.py`, `templates/index.html`, `config.yaml`, `Dockerfile` y `docker-compose.yml`).
2. **Paso de Despliegue en OMEN**:
   - Abre la terminal en esta carpeta.
   - Ejecuta:
     ```bash
     docker-compose up -d --build
     ```
3. **Verificación**:
   - Accede a `http://localhost:8086` o `http://100.95.217.45:8086` para verificar el panel de control web.
   - Revisa que las carpetas de música montadas en `docker-compose.yml` coincidan con las rutas locales de OMEN (por ejemplo, `/media` montado a la carpeta donde se almacenan las listas de Spotify).

---

## 🚀 Características del Sistema

1. **Escaneo Inteligente de Biblioteca**:
   - Lee archivos de audio (`.mp3`, `.flac`, `.m4a`, etc.) en tu servidor de medios.
   - Filtra automáticamente artistas con **3 o más canciones**.
2. **Detección de Conciertos en Madrid**:
   - Consulta Ticketmaster Discovery API y Bandsintown.
   - Detecta eventos confirmados **y también eventos pendientes de salida a la venta**.
3. **Google Calendar (Alertas a las 09:00 AM)**:
   - Agenda la fecha de **salida a la venta de entradas** con recordatorio a las **09:00 AM**.
   - Al pulsar *"¡Compré las entradas!"* en la web, añade el evento del **día del concierto** a las **09:00 AM**.
   - Genera archivo de respaldo `.ics` en `data/madrid_concerts.ics`.
4. **WhatsApp API Integration**:
   - Envía avisos automáticos desde el número `694262385` al `622609030`.
5. **Despliegue en Docker**:
   - Configuración lista con `docker-compose.yml` para correr las 24h en tu servidor **OMEN**.

---

## ⚙️ Estructura del Proyecto

```
madrid-concert-notifier/
├── README.md            # Guía e instrucciones para el usuario y Antigravity en OMEN
├── config.yaml          # Configuración principal (Rutas, WhatsApp, Umbral 3 canciones)
├── docker-compose.yml   # Despliegue en Docker
├── Dockerfile           # Imagen Docker de la aplicación
├── requirements.txt     # Dependencias de Python
├── main.py              # Servidor FastAPI y programador de tareas
├── artist_scanner.py    # Escáner de biblioteca de medios
├── concert_finder.py    # Buscador de conciertos en Madrid
├── gcalendar_service.py # Conector de Google Calendar y generador .ics
├── whatsapp_service.py  # Conector de WhatsApp API
├── templates/
│   └── index.html       # Panel web de gestión moderno
└── data/                # Persistencia de base de datos
```
