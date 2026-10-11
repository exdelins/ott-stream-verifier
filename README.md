# 🚀 OTT Stream Verifier & ClearKey DRM Checker

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Herramienta de alto rendimiento para **descarga, deduplicación inteligente y verificación profunda en tiempo real** de emisiones de vídeo **OTT** (MPEG-DASH `.mpd` con ClearKey DRM y Apple HLS `.m3u8`).

---

## 🎯 Características Principales

* 🌐 **Soporte Multifuente Automático**: Lee repositorios de GitHub (convirtiendo automáticamente enlaces `blob` a enlaces `raw`), listas M3U y endpoints JSON (ej. catálogos de eventos y canales 24/7 de DudeTV).
* 🛡️ **Solo OTT Limpio**: Filtra exclusivamente streams DASH y HLS directos de CDN (CloudFront, Akamai, Fastly, Amazon Nitro). Descarta automáticamente enlaces `.ts` o servidores IPTV clásicos propensos a bloqueos por operadores.
* 🧹 **Deduplicación Inteligente**:
  * Por URL normalizada (eliminando parámetros y tokens de sesión variables).
  * Por par **KID:KEY** (evita canales repetidos con nombres o procedencias distintas).
* 🔬 **Verificación Profunda de Vídeo ("Comprobación de que SE VE")**:
  * No se fía solo del `HTTP 200` del manifest XML (los CDNs suelen cachearlo tras terminar el evento).
  * Resuelve la plantilla de segmentos multimedia (`initialization` / `$RepresentationID$` / `.m4s`) y descarga bytes reales de vídeo. Si el segmento da error o devuelve 0 bytes, el canal se descarta.
* 🔑 **Validación Estricta de ClearKey DRM**:
  * Comprueba que la clave DRM coincida exactamente con el `default_KID` del manifest.
  * Si un manifest MPD está protegido y le falta clave, puede autoresolverla consultando bases de datos locales de claves.
* 📂 **Generación y Clasificación Automática**:
  * `deportes.m3u`: Todos los canales deportivos y eventos en directo (fútbol, F1, MotoGP, NBA, tenis, etc.).
  * `resto.m3u`: Canales generalistas, cine, series, documentales y noticias.
  * `repos_verificados.m3u`: Playlist unificada completa.
  * Formateo compatible con **TiviMate**, **OTT Navigator** y **Kodi** (`#KODIPROP`).

---

## 📦 Estructura del Proyecto

```text
ott-stream-verifier/
├── tester_repositorios.py    # Motor principal de verificación profunda y generación
├── repositorios.txt          # Lista de fuentes (GitHub, M3U y JSON)
├── canales_deseados.txt      # Filtros opcionales por palabras clave
├── config.example.json       # Plantilla de configuración opcional (Dropbox)
├── requirements.txt          # Dependencias (Python 3 standard + requests)
├── Dockerfile                # Imagen Docker lista para desplegar
├── docker-compose.yml        # Orquestación con Docker Compose
└── README.md                 # Documentación
```

---

## 🚀 Uso Rápido

### 1. Clonar el repositorio
```bash
git clone https://github.com/exdelins/ott-stream-verifier.git
cd ott-stream-verifier
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Ejecutar el verificador
```bash
python3 tester_repositorios.py --file repositorios.txt --out repos_verificados.m3u
```

### Argumentos CLI disponibles:
* `-f, --file`: Fichero de texto con las URLs de repositorios (por defecto `repositorios.txt`).
* `-o, --out`: Fichero M3U de salida (por defecto `repos_verificados.m3u`).
* `-t, --threads`: Número de hilos paralelos de verificación (por defecto `35`).
* `--timeout`: Tiempo límite en segundos para la prueba de cada stream (por defecto `3.5s`).
* `--no-dropbox`: Desactivar subida automática a Dropbox.

---

## 🐳 Despliegue con Docker

```bash
docker compose up -d
```
Las listas generadas se guardarán en la carpeta `./output/`.

---

## 📺 Compatibilidad de Reproductores

Las listas generadas utilizan las directivas estándar `#KODIPROP`:
```m3u
#EXTINF:-1 tvg-name="DAZN 1" group-title="Deportes",DAZN 1
#KODIPROP:inputstreamaddon=inputstream.adaptive
#KODIPROP:inputstream.adaptive.manifest_type=mpd
#KODIPROP:inputstream.adaptive.license_type=clearkey
#KODIPROP:inputstream.adaptive.license_key=3da197d13d754505887a04aedd17922e:0028b47ca60594991910c6f6048c51a0
https://ejemplo-cdn.net/manifest.mpd
```

* **Android TV / FireStick**: **TiviMate** o **OTT Navigator**.
* **PC / Mac**: **Kodi** con addon *InputStream Adaptive*.

---

## 📄 Licencia

Distribuido bajo la licencia MIT. Consulta el archivo `LICENSE` para más información.
