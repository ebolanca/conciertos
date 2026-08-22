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
    "emi music", "discográfica", "archivos", "various artists", "varios artistas",
    "v.a.", "va", "unknown artist", "desconocido", "compilation", "soundtrack",
    "española", "siglo xxi", "música viejuna", "viejuna", "varios", "pop", "rock"
}

class ArtistScanner:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.min_songs = self.config["scanner"].get("min_songs_threshold", 3)
        self.supported_exts = tuple(ext.lower() for ext in self.config["scanner"]["supported_extensions"])
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.artists_file = self.data_dir / "artists.json"

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
            elif kw not in ("va", "v.a.") and kw in n:
                return True
        return False

    def _extract_artist(self, file_path: Path) -> str:
        artist_name = None

        # 1. Prioridad absoluta: Parsear 'Artista - Titulo.ext' desde el nombre del archivo
        stem = file_path.stem
        if " - " in stem:
            candidate = stem.split(" - ")[0].strip()
            if candidate.lower().endswith(".temp"):
                candidate = candidate[:-5].strip()
            if not self._is_invalid_artist(candidate):
                artist_name = candidate

        # 2. Mutagen ID3 solo si el artista ID3 es válido y no es discográfica
        if not artist_name and MUTAGEN_AVAILABLE:
            try:
                audio = mutagen.File(str(file_path), easy=True)
                if audio and "artist" in audio:
                    artists = audio["artist"]
                    cand = artists[0] if isinstance(artists, list) and artists else str(artists)
                    if not self._is_invalid_artist(cand):
                        artist_name = cand
            except Exception:
                pass

        # 3. Nombre de carpeta contenedora si no es carpeta genérica / discográfica
        if not artist_name:
            parts = file_path.parts
            if len(parts) >= 2:
                folder_candidate = parts[-2].strip()
                if not self._is_invalid_artist(folder_candidate):
                    artist_name = folder_candidate

        if artist_name:
            artist_name = artist_name.strip()
            if "," in artist_name:
                artist_name = artist_name.split(",")[0].strip()
            if ";" in artist_name:
                artist_name = artist_name.split(";")[0].strip()

        if artist_name and not self._is_invalid_artist(artist_name):
            return artist_name

        return None

    def scan(self) -> dict:
        target_paths = self.get_target_paths()
        logger.info(f"Iniciando escaneo inteligente en {len(target_paths)} rutas. Umbral mínimo: {self.min_songs} canciones.")

        artist_songs = defaultdict(list)
        total_files_scanned = 0

        for target_path in target_paths:
            path_str = str(target_path)
            if not os.path.exists(path_str):
                continue
                
            for root, _, files in os.walk(path_str):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in self.supported_exts:
                        total_files_scanned += 1
                        artist = self._extract_artist(file_path)
                        if artist:
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

        logger.info(f"Escaneo inteligente completado. Pistas analizadas: {total_files_scanned}, Artistas cualificados (>= {self.min_songs} canciones): {len(qualified)}")
        return result

if __name__ == "__main__":
    scanner = ArtistScanner()
    res = scanner.scan()
    print(json.dumps(res, indent=2, ensure_ascii=False))
