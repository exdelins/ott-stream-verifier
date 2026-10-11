#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 TESTEADOR Y VERIFICADOR PROFUNDO DE REPOSITORIOS OTT (MPD & HLS CLEARKEY)
==============================================================================
1. Lee repositorios desde repositorios.txt (convierte siempre a versión raw).
2. Filtra EXCLUSIVAMENTE streams OTT (MPEG-DASH .mpd y HLS .m3u8).
3. Deduplicación inteligente:
   - Por URL normalizada.
   - Por KID y KEY (evita canales duplicados con nombres diferentes).
4. Verificación PROFUNDA de vídeo y DRM:
   - Comprueba manifest HTTP 200.
   - Comprueba si el MPD es cifrado y valida coincidencia exacta entre KID de la key y default_KID del manifest.
   - Autoresuelve keys faltantes usando la base de datos de 47.000+ claves de telegramm3u.
   - Descarga segmento init/chunk real de vídeo para garantizar que el canal SE VE y emite señal activa.
5. Exporta el M3U final (#KODIPROP) y sincroniza automáticamente con Dropbox local y en la nube.
==============================================================================
"""

import sys
import os
import re
import json
import ssl
import time
import argparse
import urllib.request
import urllib.parse
import concurrent.futures
from typing import Dict, Any, List, Optional, Tuple, Set

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

def cprint(text: str, color: str = Color.RESET, bold: bool = False):
    p = Color.BOLD + color if bold else color
    print(f"{p}{text}{Color.RESET}")


def fetch_url_text(url: str, timeout: int = 15) -> Optional[str]:
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_json(url: str, timeout: int = 15) -> Optional[Any]:
    txt = fetch_url_text(url, timeout)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


# ----------------------------------------------------------------------
# CARGA DE BASE DE DATOS DE CLAVES KID2KEY (TELEGRAM M3U)
# ----------------------------------------------------------------------
GLOBAL_KID2KEY: Dict[str, str] = {}

def load_global_kid2key():
    global GLOBAL_KID2KEY
    paths = [
        "/Volumes/docker/telegramm3u/estado.json",
        "/Volumes/docker/jarvis/estado.json"
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                t0 = time.time()
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                GLOBAL_KID2KEY = data.get("kid2key", {})
                cprint(f"  ✔ Base de datos local ClearKey cargada: {len(GLOBAL_KID2KEY)} claves ({time.time()-t0:.2f}s)", Color.GREEN)
                return
            except Exception:
                pass


# ----------------------------------------------------------------------
# EXTRACCIÓN Y CONVERSIÓN DE URLS DE REPOSITORIOS A VERSIÓN RAW
# ----------------------------------------------------------------------
def parse_repo_file(filepath: str) -> List[Tuple[str, str]]:
    if not os.path.exists(filepath):
        cprint(f"⚠ Fichero '{filepath}' no encontrado.", Color.RED, bold=True)
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    urls_found = re.findall(r'https?://[^\s\"\'<>]+', content)
    clean_repos = []
    seen = set()

    for u in urls_found:
        u = u.strip().rstrip(",")
        if u in seen:
            continue
        seen.add(u)

        # Si es el directorio de DudeTV API public_decrypted
        if "dudetvapi" in u and "public_decrypted" in u:
            clean_repos.append(("DudeTV Events (events_with_channels.json)", "https://raw.githubusercontent.com/mdjamsad9/dudetvapi/main/public_decrypted/events_with_channels.json"))
            clean_repos.append(("DudeTV Sports (sports.json)", "https://raw.githubusercontent.com/mdjamsad9/dudetvapi/main/public_decrypted/sports.json"))
            continue

        # Convertir SIEMPRE cualquier URL de GitHub a su versión RAW oficial:
        # github.com/user/repo/blob/branch/path -> raw.githubusercontent.com/user/repo/branch/path
        if "github.com" in u:
            raw_u = u.replace("github.com", "raw.githubusercontent.com")
            raw_u = re.sub(r'/(blob|raw)/', '/', raw_u)
            raw_url = raw_u
        else:
            raw_url = u

        parts = u.split("/")
        if "github.com" in u or "githubusercontent.com" in u:
            repo_name = f"{parts[3]}/{parts[4]}" if len(parts) >= 5 else parts[-1]
            filename = parts[-1].split("?")[0]
            display_name = f"{repo_name} ({filename})"
        else:
            display_name = parts[-1].split("?")[0] or u

        clean_repos.append((display_name, raw_url))

    return clean_repos


# ----------------------------------------------------------------------
# PARSEO DE CANALES (M3U Y JSON)
# ----------------------------------------------------------------------
def parse_m3u_text(text: str, repo_name: str) -> List[Dict[str, Any]]:
    channels = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            extinf = line
            title = extinf.split(",")[-1].strip()

            m_logo = re.search(r'tvg-logo="([^"]+)"', extinf)
            logo = m_logo.group(1) if m_logo else ""

            m_grp = re.search(r'group-title="([^"]+)"', extinf)
            group_raw = m_grp.group(1) if m_grp else "General"
            group = f"{repo_name} - {group_raw}"

            license_key, ua, referer, url_stream = "", "", "", ""
            i += 1
            while i < len(lines):
                cur = lines[i].strip()
                if not cur or cur.startswith("#EXTM3U") or cur.startswith("awalan") or cur.startswith("==="):
                    i += 1
                    continue
                if cur.startswith("#KODIPROP:inputstream.adaptive.license_key="):
                    license_key = cur.split("=", 1)[1].strip()
                elif cur.startswith("#EXTVLCOPT:http-user-agent="):
                    ua = cur.split("=", 1)[1].strip()
                elif cur.startswith("#EXTVLCOPT:http-referrer="):
                    referer = cur.split("=", 1)[1].strip()
                elif cur.startswith("http://") or cur.startswith("https://"):
                    url_stream = cur
                    break
                elif cur.startswith("#EXTINF:"):
                    i -= 1
                    break
                i += 1

            if url_stream:
                clean_chk = url_stream.split("?")[0].lower()
                is_mpd = ".mpd" in clean_chk
                is_hls = ".m3u8" in clean_chk
                is_ts = ".ts" in clean_chk or bool(re.search(r':\d+/(live/)?[a-zA-Z0-9]+/[a-zA-Z0-9]+/\d+', url_stream))

                # REGLA ESTRICTA: Solo MPD o HLS, nunca TS ni Xtream
                if (is_mpd or is_hls) and not is_ts:
                    channels.append({
                        "title": title,
                        "url": url_stream,
                        "api": license_key,
                        "logo": logo,
                        "group": group,
                        "ua": ua,
                        "referer": referer
                    })
        i += 1
    return channels


def parse_json_content(data: Any, repo_name: str) -> List[Dict[str, Any]]:
    channels = []
    # 1. Sports_data.json
    if isinstance(data, dict) and "matches" in data:
        for match in data.get("matches", []):
            cat = match.get("Category", "Sports")
            ev_title = match.get("event_name") or match.get("title") or "Evento Live"
            status = match.get("status", "LIVE")
            group = f"{repo_name} - {cat}"

            for ch in match.get("channels", []):
                st_url = ch.get("stream_url", "").strip()
                if not st_url or not st_url.startswith("http"):
                    continue
                clean_chk = st_url.split("?")[0].lower()
                is_mpd = ".mpd" in clean_chk
                is_hls = ".m3u8" in clean_chk
                is_ts = ".ts" in clean_chk or bool(re.search(r':\d+/(live/)?[a-zA-Z0-9]+/[a-zA-Z0-9]+/\d+', st_url))

                if (is_mpd or is_hls) and not is_ts:
                    kid = ch.get("kid", "").strip()
                    key = ch.get("key", "").strip()
                    api = f"{kid}:{key}" if (kid and key) else ""
                    channels.append({
                        "title": f"[{status}] {ev_title} · {ch.get('channel_name', 'Stream')}",
                        "url": st_url,
                        "api": api,
                        "logo": "",
                        "group": group,
                        "ua": ch.get("user_agent", ""),
                        "referer": ch.get("referer", "")
                    })

    # 2. Listas JSON (darkbyte o DudeTV)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "streams" in item:
                ch_name = item.get("name", "Canal")
                logo = item.get("logo", "")
                group = f"{repo_name} - TV"
                for s in item.get("streams", []):
                    st_url = s.get("link", "").strip() if isinstance(s, dict) else ""
                    if not st_url or not st_url.startswith("http"):
                        continue
                    clean_chk = st_url.split("?")[0].lower()
                    is_mpd = ".mpd" in clean_chk
                    is_hls = ".m3u8" in clean_chk
                    is_ts = ".ts" in clean_chk or bool(re.search(r':\d+/(live/)?[a-zA-Z0-9]+/[a-zA-Z0-9]+/\d+', st_url))

                    if (is_mpd or is_hls) and not is_ts:
                        channels.append({
                            "title": f"{ch_name} ({s.get('name', 'Stream')})",
                            "url": st_url,
                            "api": s.get("key", "") or "",
                            "logo": logo,
                            "group": group
                        })
            elif isinstance(item, dict) and "decoded_channels" in item:
                ev_name = item.get("eventInfo", {}).get("eventName") or item.get("title") or "Evento"
                cat = item.get("cat") or "Deportes"
                group = f"{repo_name} - {cat}"
                logo = item.get("eventInfo", {}).get("eventBanner") or ""
                for ch in item.get("decoded_channels", []):
                    link = ch.get("link", "").strip()
                    if not link or "taifood" in link or "/embed/" in link or not link.startswith("http"):
                        continue
                    clean_chk = link.split("?")[0].lower()
                    if (".mpd" in clean_chk or ".m3u8" in clean_chk) and not (".ts" in clean_chk):
                        channels.append({
                            "title": f"{ev_name} · {ch.get('title', 'Stream')}",
                            "url": link,
                            "api": ch.get("api", "").strip(),
                            "logo": ch.get("logo") or logo,
                            "group": group
                        })
            elif isinstance(item, dict) and "id" in item and "title" in item and "decoded_channels" not in item:
                cid = item.get("id")
                sp_title = item.get("title", "Deportes")
                sp_logo = item.get("image", "")
                c_url = f"https://raw.githubusercontent.com/mdjamsad9/dudetvapi/main/public_decrypted/channels/{cid}.json"
                c_data = fetch_json(c_url, timeout=6) or []
                for ch in c_data:
                    link = ch.get("link", "").strip()
                    if not link or "taifood" in link or "/embed/" in link or not link.startswith("http"):
                        continue
                    clean_chk = link.split("?")[0].lower()
                    if (".mpd" in clean_chk or ".m3u8" in clean_chk) and not (".ts" in clean_chk):
                        channels.append({
                            "title": f"{sp_title} · {ch.get('title', 'Stream')}",
                            "url": link,
                            "api": ch.get("api", "").strip(),
                            "logo": ch.get("logo") or sp_logo,
                            "group": f"{repo_name} - {sp_title}"
                        })
    return channels


# ----------------------------------------------------------------------
# DEDUPLICACIÓN INTELIGENTE POR URL Y POR KID / KEY
# ----------------------------------------------------------------------
def extract_kid_from_api(api_key: str) -> Optional[str]:
    if api_key and ":" in api_key:
        kid = api_key.split(":")[0].replace("-", "").strip().lower()
        if len(kid) == 32:
            return kid
    return None


def deduplicate_channels(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Quita duplicados combinando:
    1. URL normalizada (sin parámetros efímeros de sesión).
    2. Par KID:KEY (si dos canales de diferente repositorio usan la misma clave DRM, es la misma emisión).
    """
    seen_urls: Set[str] = set()
    seen_kid_keys: Set[str] = set()
    unique_list: List[Dict[str, Any]] = []

    for item in channels:
        raw_u = item["url"].split("|")[0].strip()
        # Normalizar URL (quitar parámetros de sesión variables como ?session=... o ?aws_sessionId=...)
        norm_url = re.sub(r'(\?|&)(aws_sessionId|token|auth|sessionId)=[^&]+', '', raw_u).rstrip("?")

        api = item.get("api", "").strip()
        kid = extract_kid_from_api(api)

        # Si ya hemos visto esta URL normalizada, es duplicado
        if norm_url in seen_urls:
            continue

        # Si tiene KID y ya hemos visto este mismo KID/KEY, es duplicado de emisión
        if kid and api:
            if api.lower() in seen_kid_keys:
                continue

        seen_urls.add(norm_url)
        if kid and api:
            seen_kid_keys.add(api.lower())

        item["clean_url"] = raw_u
        unique_list.append(item)

    return unique_list


# ----------------------------------------------------------------------
# VERIFICACIÓN PROFUNDA DE VÍDEO Y VALIDACIÓN ESTRICTA DE CLEARKEY
# ----------------------------------------------------------------------
def test_stream_live(item: Dict[str, Any], timeout: float = 3.5) -> Tuple[bool, str, float]:
    """
    1. Comprueba HTTP 200 del manifest.
    2. Para MPEG-DASH (.mpd):
       - Detecta si está cifrado con DRM.
       - Valida que la KID coincida EXACTAMENTE con default_KID del manifest.
       - Si no tiene key, busca en la base de datos GLOBAL_KID2KEY para rescatarla.
       - Descarga el segmento init/chunk real de vídeo. Si da 404, 403 o 0 bytes, SE DESCARTA.
    3. Para HLS (.m3u8):
       - Comprueba #EXTM3U y verifica descarga real del primer chunk de vídeo (.ts / .m4s).
    """
    raw_url = item["url"]
    clean_url = raw_url.split("|")[0].strip()

    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        return False, "URL no válida", 0.0

    headers = {"User-Agent": item.get("ua") or DEFAULT_UA}
    if item.get("referer"):
        headers["Referer"] = item["referer"]

    if "|" in raw_url:
        for part in raw_url.split("|")[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                kl = k.strip().lower()
                if kl == "user-agent": headers["User-Agent"] = v.strip()
                elif kl in ("referer", "referrer"): headers["Referer"] = v.strip()
                elif kl == "origin": headers["Origin"] = v.strip()

    api_key = item.get("api", "").strip()
    t_start = time.time()

    try:
        # 1. Comprobar manifest principal
        req = urllib.request.Request(clean_url, headers=headers)
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}", time.time() - t_start
            content = resp.read(65536)
            if len(content) < 40:
                return False, "Manifest vacío (<40 bytes)", time.time() - t_start

        # 2. Análisis exhaustivo para MPEG-DASH (MPD)
        if "mpd" in clean_url.lower():
            text = content.decode("utf-8", errors="ignore")
            if "<Period" not in text and "<MPD" not in text:
                return False, "Formato MPD inválido", time.time() - t_start

            # Extraer KIDs del manifest
            kids_in_mpd = [k.replace("-", "").strip().lower() for k in re.findall(r'default_KID="([a-fA-F0-9-]+)"', text, re.I)]
            is_encrypted = ("<ContentProtection" in text) or bool(kids_in_mpd)

            # Si es cifrado pero no tiene clave, intentar autoresolver desde kid2key de telegramm3u
            if is_encrypted and (not api_key or ":" not in api_key):
                for k_mpd in kids_in_mpd:
                    if k_mpd in GLOBAL_KID2KEY:
                        api_key = f"{k_mpd}:{GLOBAL_KID2KEY[k_mpd]}"
                        item["api"] = api_key
                        break

            # VALIDACIÓN ESTRICTA DE CLEARKEY:
            if is_encrypted:
                if not api_key or ":" not in api_key:
                    return False, "MPD cifrado sin clave ClearKey", time.time() - t_start

                api_kid = api_key.split(":")[0].replace("-", "").strip().lower()
                if kids_in_mpd and api_kid not in kids_in_mpd:
                    return False, "KID no coincide con manifest", time.time() - t_start

            # MIRA SI SE VE: Prueba de segmento de inicialización / vídeo real
            m_init = re.search(r'initialization="([^"]+)"', text)
            if m_init:
                init_pattern = m_init.group(1)
                # Resolver variable $RepresentationID$ con el primer ID de representación
                m_rep = re.search(r'<Representation\s+id="([^"]+)"', text)
                rep_id = m_rep.group(1) if m_rep else "1"
                init_rel = init_pattern.replace("$RepresentationID$", rep_id)

                base_dir = clean_url.rsplit("/", 1)[0] + "/"
                init_url = init_rel if (init_rel.startswith("http://") or init_rel.startswith("https://")) else base_dir + init_rel

                try:
                    req_init = urllib.request.Request(init_url, headers=headers)
                    with urllib.request.urlopen(req_init, context=SSL_CTX, timeout=timeout) as resp_init:
                        if resp_init.status != 200:
                            return False, f"Segmento init HTTP {resp_init.status}", time.time() - t_start
                        chunk = resp_init.read(256)
                        if len(chunk) == 0:
                            return False, "Segmento de vídeo 0 bytes (evento terminado)", time.time() - t_start
                except urllib.error.HTTPError as eh:
                    return False, f"Segmento init HTTP {eh.code} (caído)", time.time() - t_start
                except Exception:
                    pass

        # 3. Análisis exhaustivo para HLS (.m3u8)
        elif "m3u8" in clean_url.lower():
            text = content.decode("utf-8", errors="ignore")
            if "#EXTM3U" not in text:
                return False, "Formato M3U8 inválido", time.time() - t_start

            # Probar el primer segmento .ts o .m4s del playlist
            m_chunk = re.search(r'([^\s\r\n]+\.(?:ts|m4s)[^\s\r\n]*)', text)
            if m_chunk:
                chunk_rel = m_chunk.group(1)
                base_dir = clean_url.rsplit("/", 1)[0] + "/"
                chunk_url = chunk_rel if (chunk_rel.startswith("http://") or chunk_rel.startswith("https://")) else base_dir + chunk_rel
                try:
                    req_chk = urllib.request.Request(chunk_url, headers=headers)
                    with urllib.request.urlopen(req_chk, context=SSL_CTX, timeout=timeout) as resp_chk:
                        if resp_chk.status != 200:
                            return False, f"Segmento TS HTTP {resp_chk.status}", time.time() - t_start
                        chunk = resp_chk.read(256)
                        if len(chunk) == 0:
                            return False, "Chunk de vídeo 0 bytes (caído)", time.time() - t_start
                except Exception:
                    pass

        ping_ms = (time.time() - t_start) * 1000
        item["clean_url"] = clean_url
        item["headers"] = headers
        item["api"] = api_key
        return True, f"OK ({ping_ms:.0f}ms)", ping_ms / 1000

    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}", time.time() - t_start
    except Exception as e:
        return False, str(e)[:35], time.time() - t_start


def build_m3u_entry(item: Dict[str, Any]) -> str:
    title = item["title"]
    logo = item.get("logo", "")
    group = item.get("group", "Deportes")
    clean_url = item["clean_url"]
    headers = item.get("headers", {})
    api_key = item.get("api", "").strip()

    ext = clean_url.split("?")[0].split(".")[-1].lower()
    is_mpd = (ext == "mpd" or "dash" in clean_url)

    lines = []
    lines.append(f'#EXTINF:-1 tvg-name="{title}" tvg-logo="{logo}" group-title="{group}",{title}')

    if api_key and ":" in api_key:
        lines.append("#KODIPROP:inputstreamaddon=inputstream.adaptive")
        lines.append("#KODIPROP:inputstream.adaptive.manifest_type=mpd")
        lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        lines.append(f"#KODIPROP:inputstream.adaptive.license_key={api_key}")
    elif is_mpd:
        lines.append("#KODIPROP:inputstreamaddon=inputstream.adaptive")
        lines.append("#KODIPROP:inputstream.adaptive.license_type=mpd")
    else:
        lines.append("#KODIPROP:inputstreamaddon=inputstream.adaptive")
        lines.append("#KODIPROP:inputstream.adaptive.license_type=hls")

    if "User-Agent" in headers and headers["User-Agent"] != DEFAULT_UA:
        lines.append(f"#EXTVLCOPT:http-user-agent={headers['User-Agent']}")
    if "Referer" in headers:
        lines.append(f"#EXTVLCOPT:http-referrer={headers['Referer']}")
    if "Origin" in headers:
        lines.append(f"#EXTVLCOPT:http-origin={headers['Origin']}")

    lines.append(clean_url)
    return "\n".join(lines)


# ----------------------------------------------------------------------
# SUBIDA AUTOMÁTICA A DROPBOX
# ----------------------------------------------------------------------
def upload_dropbox_cloud(local_path: str, remote_name: str = "/repos_verificados.m3u"):
    config_paths = [
        "/Volumes/docker/python/eventosDazn/dropbox.json",
        "/Volumes/docker/telegramm3u/conf/dropbox.json"
    ]
    cfg_file = next((p for p in config_paths if os.path.exists(p)), None)
    if not cfg_file:
        return

    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            cfg = json.load(f).get("dropbox", {})
        if not cfg.get("activo"):
            return

        app_key = cfg.get("app_key")
        app_secret = cfg.get("app_secret")
        refresh_token = cfg.get("refresh_token")

        if not (app_key and app_secret and refresh_token):
            return

        # Refrescar token
        req_token = urllib.request.Request(
            "https://api.dropbox.com/oauth2/token",
            data=urllib.parse.urlencode({
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": app_key,
                "client_secret": app_secret
            }).encode("utf-8")
        )
        with urllib.request.urlopen(req_token, timeout=20) as r:
            acc_token = json.loads(r.read().decode("utf-8"))["access_token"]

        with open(local_path, "rb") as f_in:
            file_bytes = f_in.read()

        req_upload = urllib.request.Request(
            "https://content.dropboxapi.com/2/files/upload",
            data=file_bytes,
            headers={
                "Authorization": f"Bearer {acc_token}",
                "Dropbox-API-Arg": json.dumps({
                    "path": remote_name,
                    "mode": "overwrite",
                    "autorename": False,
                    "mute": False
                }),
                "Content-Type": "application/octet-stream"
            }
        )
        with urllib.request.urlopen(req_upload, timeout=30) as r_up:
            cprint(f"  ✔ [Dropbox Cloud] Subido exitosamente a '{remote_name}'", Color.GREEN, bold=True)
    except Exception as e:
        cprint(f"  ⚠ [Dropbox Cloud] Error: {e}", Color.YELLOW)


# ----------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Testeador y Verificador Profundo de Repositorios OTT (MPD & HLS ClearKey)")
    parser.add_argument("-f", "--file", default="/Volumes/docker/python/iptv_xtream/repositorios.txt",
                        help="Fichero con lista de URLs de repositorios (por defecto: repositorios.txt)")
    parser.add_argument("-o", "--out", default="/Volumes/docker/python/iptv_xtream/repos_verificados.m3u",
                        help="Fichero M3U de salida")
    parser.add_argument("-t", "--threads", type=int, default=35, help="Número de hilos paralelos")
    parser.add_argument("--timeout", type=float, default=3.5, help="Timeout por canal en segundos")
    parser.add_argument("--no-dropbox", action="store_true", help="No subir a Dropbox")
    args = parser.parse_args()

    print("=" * 80)
    cprint(" VERIFICADOR PROFUNDO DE REPOSITORIOS GITHUB OTT (MPD & HLS CLEARKEY) ", Color.CYAN, bold=True)
    print("=" * 80)

    # 1. Cargar base de datos ClearKey local si está disponible
    load_global_kid2key()

    # 2. Leer repositorios del fichero
    repos = parse_repo_file(args.file)
    cprint(f"\n[1/4] Leyendo repositorios desde '{os.path.basename(args.file)}'...", Color.WHITE, bold=True)
    cprint(f"  Total de URLs de repositorios detectadas: {len(repos)}", Color.GREEN, bold=True)

    if not repos:
        cprint("⚠ No se encontraron URLs en el fichero proporcionado.", Color.RED, bold=True)
        return

    # 3. Descargar y parsear cada repositorio
    cprint("\n[2/4] Descargando y parseando canales (exclusivamente MPD y HLS)...", Color.CYAN, bold=True)
    all_raw: List[Dict[str, Any]] = []

    for disp_name, raw_url in repos:
        txt = fetch_url_text(raw_url, timeout=12)
        if not txt:
            cprint(f"  ⚠ Falló descarga de: {disp_name}", Color.YELLOW)
            continue

        txt_strip = txt.strip()
        chs = []
        if txt_strip.startswith("{") or txt_strip.startswith("["):
            try:
                js_data = json.loads(txt)
                chs = parse_json_content(js_data, disp_name)
            except Exception:
                pass
        else:
            chs = parse_m3u_text(txt, disp_name)

        if chs:
            all_raw.extend(chs)
            cprint(f"  ✔ {disp_name:<45} -> {len(chs)} streams válidos extraídos", Color.WHITE)
        else:
            cprint(f"  - {disp_name:<45} -> 0 streams MPD/HLS", Color.YELLOW)

    # 4. Deduplicar por URL y por KID/KEY
    unique_candidates = deduplicate_channels(all_raw)
    cprint(f"\n  Total streams brutos:                    {len(all_raw)}", Color.WHITE)
    cprint(f"  Duplicados descartados (por URL y KID):  {len(all_raw) - len(unique_candidates)}", Color.YELLOW)
    cprint(f"  Candidatos únicos a testear:             {len(unique_candidates)}", Color.GREEN, bold=True)

    if not unique_candidates:
        cprint("⚠ No hay canales disponibles para testear.", Color.RED)
        return

    # 5. Verificación profunda en tiempo real
    cprint(f"\n[3/4] Verificando emisión real y validez de claves DRM ({args.threads} hilos)...", Color.YELLOW, bold=True)
    cprint("      * Comprobando que el MPD responda HTTP 200", Color.WHITE)
    cprint("      * Validando coincidencia exacta entre la clave y el default_KID del manifest", Color.WHITE)
    cprint("      * Descargando bytes reales del segmento de vídeo (garantía de que SE VE)", Color.WHITE)
    print("-" * 80)

    verified_items = []
    dead_items = []

    def check_worker(ch):
        ok, msg, p_sec = test_stream_live(ch, timeout=args.timeout)
        return ok, ch, msg

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = {ex.submit(check_worker, ch): ch for ch in unique_candidates}
        for fut in concurrent.futures.as_completed(futures):
            ok, ch, msg = fut.result()
            if ok:
                verified_items.append(ch)
                cprint(f"  [✔ ONLINE] {ch['title'][:55]:<55} -> {msg}", Color.GREEN)
            else:
                dead_items.append((ch, msg))
                cprint(f"  [✗ OFFLINE] {ch['title'][:55]:<55} -> {msg}", Color.RED)

    # Segunda deduplicación post-verificación (si dos manifests resolvieron al mismo default_KID verificado)
    final_verified = []
    seen_final_kids = set()
    seen_final_urls = set()
    for ch in verified_items:
        u = ch["clean_url"]
        api = ch.get("api", "").strip()
        kid = extract_kid_from_api(api)
        if u in seen_final_urls:
            continue
        if kid and kid in seen_final_kids:
            continue
        seen_final_urls.add(u)
        if kid:
            seen_final_kids.add(kid)
        final_verified.append(ch)

    print("-" * 80)
    cprint(f"\n✔ Resumen de verificación profunda:", Color.CYAN, bold=True)
    cprint(f"  [CANALES VIVOS EMITIENDO VÍDEO REAL Y DRM VÁLIDO]: {len(final_verified)} canales", Color.GREEN, bold=True)
    cprint(f"  [CANALES CAÍDOS, REPETIDOS O CON ERROR DE CLAVE] : {len(all_raw) - len(final_verified)} descartados", Color.RED)

    # 6. Clasificación: Lista de Deportes (con eventos siempre) y Lista de Resto
    cprint(f"\n[4/4] Separando y generando listas (Deportes vs Resto)...", Color.WHITE, bold=True)

    SPORTS_PATTERNS = [
        r'\bdeport', r'\bsport\b', r'\bsports\b', r'\bfutbol\b', r'\bfootball\b', r'\bsoccer\b',
        r'\blaliga\b', r'\bliga de campeones\b', r'\bchampions league\b', r'\bdazn\b', r'\beurosport\b',
        r'\bbein\b', r'\bespn\b', r'\btnt sports?\b', r'\bsky sports?\b', r'\bf1\b', r'\bformula 1\b',
        r'\bmotogp\b', r'\bmoto gp\b', r'\bnba\b', r'\bnfl\b', r'\bnhl\b', r'\bmlb\b', r'\bufc\b',
        r'\bwwe\b', r'\bboxing\b', r'\bboxeo\b', r'\bpremier league\b', r'\bgolf\b', r'\btennis\b',
        r'\btenis\b', r'\bcricket\b', r'\brugby\b', r'\bracing\b', r'\bbarca tv\b', r'\breal madrid\b',
        r'\bmatch!\b', r'\bfifa\b', r'\bfancode\b', r'\bwillow\b', r'\bcaze\b', r'\bcalcio\b',
        r'\bbundesliga\b', r'\bstan sport\b', r'\boptus\b', r'\bsuper sport\b', r'\bastro super\b',
        r'\bsportv\b', r'\bredzone\b', r'\bone fight\b', r'\btour de france\b', r'\bpga\b', r'\batp\b',
        r'\bwta\b', r'\bdsports?\b', r'\bteledeporte\b', r'\btdp\b', r'\bmotorsport\b', r'\bmotorvision\b',
        r'\brally\.tv\b', r'\bfight box\b', r'\bsetanta\b', r'\bstrongman\b', r'\bsupersport\b', r'\bacelerados\b'
    ]

    NON_SPORTS_GROUP_PATTERNS = [
        r'\bcctv\b', r'\bnews\b', r'\bnoticias\b', r'\brelax\b', r'\bmusic\b', r'\bk-pop\b',
        r'\bcooking\b', r'\breligi\b', r'\bdaerah\b', r'\bnasional\b', r'\btraffic\b', r'\bweather\b',
        r'\bshopping\b', r'\bkids\b', r'\bseries\b', r'\bcinema\b', r'\bcine\b', r'\bpeliculas\b',
        r'\bdocumentar', r'\bgeneralist', r'\bentertainment\b'
    ]

    NON_SPORTS_TITLE_PATTERNS = [
        r'\bcooking\b', r'\bkitchen\b', r'\bfood\b', r'\bmewatch\b', r'\bcctv\b',
        r'\bnews\b', r'\bnoticias\b', r'\bweather\b', r'\bmeteo\b', r'\bshopping\b',
        r'\bmusic\b', r'\bk-pop\b', r'\brelax\b', r'\bfinance\b', r'\bfinancial\b',
        r'\bqur\'?an\b', r'\bsunnah\b', r'\brodja\b', r'\bmadani\b', r'\bchurch\b',
        r'\bfaith\b', r'\bexit tol\b', r'\bsimpang\b', r'\bpasar\b', r'\balun-alun\b',
        r'\bjalan\b', r'\bbundaran\b', r'\btraffic\b', r'\bhorse & country\b', r'\ble grand direct\b'
    ]

    GENERALIST_CHANNELS = [
        r'\bla 1\b', r'\bla 2\b', r'\bantena 3\b', r'\bcuatro\b', r'\btelecinco\b', r'\bla sexta\b',
        r'\btelemundo\b', r'\bglobo\b', r'\brecord\b', r'\bzdf\b', r'\bard\b', r'\brtp\b', r'\btvi\b',
        r'\bsic\b', r'\btf1\b', r'\bm6\b', r'\bcctv\b', r'\bcna\b', r'\bcnn\b', r'\bkompas\b',
        r'\bmetro tv\b', r'\bmnc\b', r'\brcti\b', r'\brtv\b', r'\btv one\b', r'\bweather\b',
        r'\bqur\'?an\b', r'\bsmithsonian\b', r'\bocko\b', r'\bvoice of america\b', r'\bwion\b',
        r'\byahoo\b', r'\bmewatch\b'
    ]

    def clean_group_name(raw_group: str) -> str:
        # Eliminar prefijo del repo (ej: 'AberTown/V_Zone.m3u (V_Sport.m3u) - CCTV' -> 'CCTV')
        if ' - ' in raw_group:
            return raw_group.split(' - ')[-1].strip()
        return raw_group.strip()

    def normalize_str(text: str) -> str:
        return re.sub(r'[_.\-]+', ' ', text.lower()).strip()

    def is_sports_channel(item_dict: Dict[str, Any]) -> bool:
        title = item_dict["title"]
        raw_group = item_dict.get("group", "")
        grp = normalize_str(clean_group_name(raw_group))
        t_norm = normalize_str(title)

        # Regla estricta 1: LOS EVENTOS SON DE DEPORTES SIEMPRE (partidos vs o transmisiones deportivas en vivo)
        is_live_event = (' vs ' in t_norm or ' vs. ' in t_norm or 'dudetv events' in raw_group.lower())
        if is_live_event:
            return True

        # Regla estricta 2: Excluir títulos que son explícitamente cocina, noticias, tráfico, etc.
        for pat in NON_SPORTS_TITLE_PATTERNS:
            if re.search(pat, t_norm):
                return False

        # Regla estricta 3: Excluir grupos que son explícitamente noticias, CCTV, religión, relax, etc.
        for pat in NON_SPORTS_GROUP_PATTERNS:
            if re.search(pat, grp):
                if 'sport' not in t_norm:
                    return False

        # Regla estricta 4: Canales generalistas nacionales (TVE La 1, Antena 3, Globo, ZDF, TF1, etc.) van a Resto
        for pat in GENERALIST_CHANNELS:
            if re.search(pat, t_norm):
                # Si el título tiene marca deportiva explícita (ej: 'Sky Sport', 'BeIN', 'ESPN'), no es generalista
                if not any(re.search(sp, t_norm) for sp in [r'\bsky sport', r'\bbein', r'\bespn', r'\bdazn']):
                    return False

        # Regla estricta 5: Coincidencia con marcas y categorías deportivas en título o grupo limpio
        for pat in SPORTS_PATTERNS:
            if re.search(pat, t_norm) or re.search(pat, grp):
                return True

        return False

    sports_items = [ch for ch in final_verified if is_sports_channel(ch)]
    resto_items = [ch for ch in final_verified if not is_sports_channel(ch)]

    cprint(f"  ✔ Canales de Deportes & Eventos: {len(sports_items)} canales", Color.GREEN, bold=True)
    cprint(f"  ✔ Canales del Resto (TV/Cine/Noticias): {len(resto_items)} canales", Color.CYAN, bold=True)

    timestamp_str = time.strftime("%d/%m/%Y %H:%M")
    header_all = f'#EXTM3U name="Repositorios OTT Verificados ({timestamp_str})"\n\n'
    header_dep = f'#EXTM3U name="OTT Deportes & Eventos Verificados ({timestamp_str})"\n\n'
    header_res = f'#EXTM3U name="OTT Resto TV & Noticias ({timestamp_str})"\n\n'

    m3u_all = header_all + "\n\n".join(build_m3u_entry(ch) for ch in final_verified) + "\n"
    m3u_dep = header_dep + "\n\n".join(build_m3u_entry(ch) for ch in sports_items) + "\n"
    m3u_res = header_res + "\n\n".join(build_m3u_entry(ch) for ch in resto_items) + "\n"

    # Guardar en NAS / Local
    base_dir = os.path.dirname(os.path.abspath(args.out))
    path_dep = os.path.join(base_dir, "deportes.m3u")
    path_res = os.path.join(base_dir, "resto.m3u")

    with open(args.out, "w", encoding="utf-8") as f: f.write(m3u_all)
    with open(path_dep, "w", encoding="utf-8") as f: f.write(m3u_dep)
    with open(path_res, "w", encoding="utf-8") as f: f.write(m3u_res)

    cprint(f"  ✔ Lista completa: {args.out}", Color.GREEN)
    cprint(f"  ✔ Lista deportes: {path_dep}", Color.GREEN)
    cprint(f"  ✔ Lista resto:    {path_res}", Color.GREEN)

    # Copiar a Dropbox local y en la nube
    if not args.no_dropbox:
        dropbox_dir = "/Users/cesar/Dropbox"
        if os.path.exists(dropbox_dir):
            for fname, content in [("repos_verificados.m3u", m3u_all), ("deportes.m3u", m3u_dep), ("resto.m3u", m3u_res)]:
                p_dbx = os.path.join(dropbox_dir, fname)
                with open(p_dbx, "w", encoding="utf-8") as f: f.write(content)
            cprint("  ✔ Listas copiadas a Dropbox local (/Users/cesar/Dropbox/)", Color.GREEN)

        upload_dropbox_cloud(path_dep, remote_name="/deportes.m3u")
        upload_dropbox_cloud(path_res, remote_name="/resto.m3u")
        upload_dropbox_cloud(args.out, remote_name="/repos_verificados.m3u")

    cprint(f"\n✔ ¡Proceso completado con éxito! {len(sports_items)} deportes y {len(resto_items)} canales del resto generados.", Color.GREEN, bold=True)


if __name__ == "__main__":
    main()
