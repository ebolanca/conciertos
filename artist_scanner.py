import os
import json
import logging
from pathlib import Path
from collections import defaultdict
import yaml

try:
    import mutagen
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

RECORD_LABEL_KEYWORDS = {
    "warner music", "warner", "codiscos", "sony music", "universal music",
    "emi music", "discográfica", "discografica", "archivos", "various artists", "varios artistas",
    "v.a.", "va", "unknown artist", "desconocido", "compilation", "soundtrack", "bso",
    "española", "espanola", "siglo xxi", "siglo xxi roberto", "música viejuna", "musica viejuna",
    "música viejuna roberto", "musica viejuna roberto", "viejuna", "viejuna roberto",
    "dance", "música latina", "musica latina", "latina", "varios", "pop", "rock",
    "canal mecano", "happy charlie"
}

DEFAULT_TARGET_PLAYLISTS = [
    "Música viejuna Roberto",
    "Siglo XXI Roberto",
    "Española",
    "Música latina",
    "Dance"
]

DEFAULT_EXCLUDED_PLAYLISTS = [
    "Música viejuna",
    "Siglo XXI"
]

class ArtistScanner:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.min_songs = self.config["scanner"].get("min_songs_threshold", 3)
        self.supported_exts = tuple(ext.lower() for ext in self.config["scanner"].get("supported_extensions", [".mp3", ".flac", ".m4a", ".ogg", ".wav", ".aac"]))
        
        self.target_playlists = self.config["scanner"].get("target_playlists", DEFAULT_TARGET_PLAYLISTS)
        self.excluded_playlists = [p.strip().lower() for p in self.config["scanner"].get("excluded_playlists", DEFAULT_EXCLUDED_PLAYLISTS)]

        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.artists_file = self.data_dir / "artists.json"

    def get_spotdl_cache_path(self) -> Path:
        candidates = self.config["scanner"].get("spotdl_cache_files", [])
        if isinstance(candidates, str):
            candidates = [candidates]
        
        default_candidates = [
            "/app/spotdl_cache/tracks_cache.json",
            "D:\\Docker\\media-server\\spotdl-sync\\cache\\tracks_cache.json",
            "D:/Docker/media-server/spotdl-sync/cache/tracks_cache.json",
            r"\\100.95.217.45\omen D\Docker\media-server\spotdl-sync\cache\tracks_cache.json"
        ]
        for c in list(candidates) + default_candidates:
            p = Path(c)
            if p.exists():
                return p
        return None

    def get_target_paths(self) -> list:
        paths = []
        docker_path = Path(self.config["scanner"].get("docker_music_folder", "/media"))
        if docker_path.exists():
            paths.append(docker_path)
            return paths

        raw_folders = self.config["scanner"].get("music_folder", [])
        if isinstance(raw_folders, str):
            raw_folders = [raw_folders]

        for folder_str in raw_folders:
            p = Path(folder_str)
            if p.exists() or os.path.exists(folder_str):
                paths.append(p)
            else:
                logger.warning(f"Ruta no encontrada o inaccesible: {folder_str}")

        return paths

    def _is_invalid_artist(self, name: str) -> bool:
        if not name or len(name.strip()) < 2:
            return True
        n = name.strip().lower()
        if n in RECORD_LABEL_KEYWORDS:
            return True
        for kw in RECORD_LABEL_KEYWORDS:
            if kw in ("va", "v.a.") and n == kw:
                return True
            elif kw not in ("va", "v.a.") and kw == n:
                return True
            elif len(kw) > 6 and kw in n:
                return True
        return False

    def clean_artist_name(self, raw_artist: str) -> str:
        if not raw_artist:
            return ""
        cand = raw_artist.strip()
        for sep in [",", ";", "/", " feat.", " ft.", " feat ", " ft "]:
            if sep in cand.lower():
                idx = cand.lower().find(sep)
                cand = cand[:idx].strip()
        cand = cand.strip()
        if self._is_invalid_artist(cand):
            return ""
        return cand

    def _extract_artist(self, file_path: Path) -> str:
        artist_name = None

        # 1. Prioridad absoluta: Parsear 'Artista - Titulo.ext' desde el nombre del archivo
        stem = file_path.stem
        if " - " in stem:
            candidate = stem.split(" - ")[0].strip()
            if candidate.lower().endswith(".temp"):
                candidate = candidate[:-5].strip()
            candidate = self.clean_artist_name(candidate)
            if candidate:
                artist_name = candidate

        # 2. Mutagen ID3 solo si el artista ID3 es válido y no es discográfica / playlist
        if not artist_name and MUTAGEN_AVAILABLE:
            try:
                audio = mutagen.File(str(file_path), easy=True)
                if audio and "artist" in audio:
                    artists = audio["artist"]
                    cand = artists[0] if isinstance(artists, list) and artists else str(artists)
                    cand = self.clean_artist_name(cand)
                    if cand:
                        artist_name = cand
            except Exception:
                pass

        if artist_name and not self._is_invalid_artist(artist_name):
            return artist_name

        return None

    def scan(self) -> dict:
        artist_songs = defaultdict(list)
        total_files_scanned = 0

        # 1. FUENTE PRINCIPAL: Caché sincronizado de Spotify (spotdl-sync tracks_cache.json)
        spotdl_cache = self.get_spotdl_cache_path()
        if spotdl_cache:
            logger.info(f"Cargando canciones de Spotify desde spotdl cache: {spotdl_cache}")
            try:
                with open(spotdl_cache, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)

                for pl_name in self.target_playlists:
                    tracks = cache_data.get(pl_name, [])
                    logger.info(f" -> Playlist '{pl_name}': {len(tracks)} canciones.")
                    for item in tracks:
                        total_files_scanned += 1
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            art = self.clean_artist_name(item[0])
                            tit = item[1]
                            if art:
                                song_str = f"{art} - {tit}"
                                if song_str not in artist_songs[art]:
                                    artist_songs[art].append(song_str)
            except Exception as e:
                logger.error(f"Error leyendo spotdl cache: {e}")

        # 2. FUENTE SECUNDARIA: Archivos locales en disco
        target_paths = self.get_target_paths()
        logger.info(f"Escaneando carpetas en disco ({len(target_paths)} rutas). Umbral mínimo: {self.min_songs} canciones.")

        for target_path in target_paths:
            path_str = str(target_path)
            if not os.path.exists(path_str):
                continue
                
            for root, dirnames, files in os.walk(path_str):
                # Filtrar directorios para omitir listas antiguas (ej: 'Música viejuna', 'Siglo XXI')
                dirnames[:] = [
                    d for d in dirnames 
                    if d.strip().lower() not in self.excluded_playlists
                ]

                current_folder_name = Path(root).name.strip().lower()
                if current_folder_name in self.excluded_playlists:
                    continue

                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in self.supported_exts:
                        artist = self._extract_artist(file_path)
                        if artist:
                            if not spotdl_cache:
                                total_files_scanned += 1
                            if file_path.name not in artist_songs[artist]:
                                artist_songs[artist].append(file_path.name)

        qualified = {}
        for artist, songs in artist_songs.items():
            if len(songs) >= self.min_songs:
                qualified[artist] = {
                    "song_count": len(songs),
                    "songs_sample": songs[:5]
                }

        result = {
            "total_files_scanned": total_files_scanned,
            "total_unique_artists": len(artist_songs),
            "min_songs_threshold": self.min_songs,
            "qualified_artists_count": len(qualified),
            "qualified_artists": dict(sorted(qualified.items(), key=lambda x: x[1]["song_count"], reverse=True))
        }

        with open(self.artists_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Escaneo completado con éxito. Pistas analizadas: {total_files_scanned}, Artistas cualificados (>= {self.min_songs} canciones): {len(qualified)}")
        return result

if __name__ == "__main__":
    scanner = ArtistScanner()
    res = scanner.scan()
    print(json.dumps(res, indent=2, ensure_ascii=False))
