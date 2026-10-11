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
* 📂 **Generación y Clasificación Automática Afinada**:
  * `deportes.m3u`: Todos los canales deportivos 24/7 y eventos en directo (fútbol, F1, MotoGP, NBA, tenis, etc.) sin cadenas generalistas ni cámaras de tráfico.
  * `resto.m3u`: Canales generalistas (La 1, Antena 3, Globo, ZDF...), cine, series, documentales y noticias.
  * `repos_verificados.m3u`: Playlist unificada completa.
  * Formateo compatible con **TiviMate**, **OTT Navigator** y **Kodi** (`#KODIPROP`).

---

## 📦 Estructura del Proyecto

```text
ott-stream-verifier/
├── tester_repositorios.py    # Motor principal de verificación profunda y generación
├── repositorios.txt          # Lista de fuentes (GitHub, M3U y JSON)
├── canales_deseados.txt      # Filtros opcionales por palabras clave
├── config.example.json       # Plantilla de configuración opcional
├── requirements.txt          # Dependencias (Python 3 standard + requests)
├── Dockerfile                # Imagen Docker lista para desplegar
├── docker-compose.yml        # Orquestación con Docker Compose
└── README.md                 # Manual de configuración y uso
```

---

## ⚙️ Manual de Configuración y Uso

### 1. Configuración de Fuentes (`repositorios.txt`)

En `repositorios.txt` introduces las URLs de los repositorios o APIs que deseas comprobar. Puedes usar comentarios con `#` y un enlace por línea.

#### Formatos admitidos:
* **GitHub M3U Web o Raw**: Pega enlaces directos de GitHub (ej. `https://github.com/usuario/repo/blob/main/lista.m3u`), el script los transforma a enlaces `raw` automáticamente.
* **APIs JSON (DudeTV / Eventos)**: Endpoints que devuelven JSONs con listas de canales y transmisiones deportivas.
* **URLs M3U directas**: Cualquier servidor o CDN con streams `.mpd` o `.m3u8`.

#### Ejemplo de `repositorios.txt`:
```text
# === Repositorios GitHub con streams OTT ===
https://github.com/AberTown/V_Zone.m3u/blob/main/V_Sport.m3u
https://github.com/iprtl/m3u/blob/master/Freetv.m3u
https://github.com/shareext-reborn/Shareext-UpdateFilesSports.m3u/blob/main/Shareext@playlist

# === Endpoints JSON de Eventos y Deportes ===
https://raw.githubusercontent.com/mdjamsad9/dudetvapi/main/public_decrypted/events_with_channels.json
https://raw.githubusercontent.com/mdjamsad9/dudetvapi/main/public_decrypted/sports.json
```

---

### 2. Instalación y Requisitos

Requiere **Python 3.8 o superior**.

```bash
# 1. Clonar el repositorio
git clone https://github.com/exdelins/ott-stream-verifier.git
cd ott-stream-verifier

# 2. Instalar dependencias
pip install -r requirements.txt
```

---

### 3. Ejecución por Línea de Comandos (CLI)

```bash
python3 tester_repositorios.py [OPCIONES]
```

#### Parámetros disponibles:
| Parámetro | Por defecto | Descripción |
| :--- | :---: | :--- |
| `-f, --file` | `repositorios.txt` | Ruta del fichero con las URLs de fuentes. |
| `-o, --out` | `repos_verificados.m3u` | Ruta de salida de la lista completa unificada. |
| `-t, --threads` | `35` | Número de hilos simultáneos para testeo en paralelo. |
| `--timeout` | `3.5` | Tiempo límite en segundos para la descarga de manifests y fragmentos de vídeo. |
| `--no-dropbox` | `False` | Desactiva la subida automática a Dropbox. |

#### Ejemplos de uso:
```bash
# Verificación rápida con 35 hilos en paralelo (recomendado)
python3 tester_repositorios.py --file repositorios.txt --threads 35 --no-dropbox

# Verificación conservadora con timeout más alto
python3 tester_repositorios.py --threads 20 --timeout 6.0 --no-dropbox
```

---

### 4. Clasificación de Listas Resultantes

El script genera 3 archivos `.m3u` en la misma carpeta:

1. **`deportes.m3u`**: 
   - Canales deportivos 24/7 (DAZN 1-5, Eurosport, beIN Sports, LaLiga, Movistar Deportes, Sky Sports F1/Premier/Golf, Fox Sports 1-3, ESPN, NBA TV, etc.).
   - Eventos deportivos en directo (Fórmula 1, MotoGP, UFC, WWE, Premier League, Champions League, NFL).
   - **Filtro estricto anti-generalistas**: Purga automática de canales nacionales, noticias, cámaras de tráfico o canales de relajación.
2. **`resto.m3u`**: 
   - Televisión generalista (La 1, La 2, Antena 3, Cuatro, Telecinco, La Sexta, Globo, ZDF, TF1, etc.).
   - Canales de noticias 24h (CNN, BBC, TVRI), series, cine, música y documentales.
3. **`repos_verificados.m3u`**: 
   - Lista completa con la totalidad de los streams vivos que superaron el test de vídeo.

---

### 5. Automatización en Servidor Linux (Cron cada 30 min)

Para mantener tus listas siempre actualizadas y sin enlaces caídos en tu VPS o servidor:

1. Crea el script de ejecución `/root/actualizar_repos_ott.sh`:
```bash
#!/bin/bash
set -e
LOG='/var/log/actualizar_repos_ott.log'
NOW=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$NOW] === Iniciando actualización OTT ===" >> "$LOG"

cd /root
python3 /root/tester_repositorios.py \
  --file /root/repositorios.txt \
  --out /var/www/html/repos_verificados.m3u \
  --threads 35 \
  --no-dropbox >> "$LOG" 2>&1

chown www-data:www-data /var/www/html/repos_verificados.m3u /var/www/html/deportes.m3u /var/www/html/resto.m3u 2>/dev/null || true
chmod 644 /var/www/html/repos_verificados.m3u /var/www/html/deportes.m3u /var/www/html/resto.m3u 2>/dev/null || true

NOW_END=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$NOW_END] === Fin de actualización OTT ===" >> "$LOG"
```

2. Asigna permisos de ejecución:
```bash
chmod +x /root/actualizar_repos_ott.sh
```

3. Programa la tarea en `crontab -e`:
```text
*/30 * * * * /root/actualizar_repos_ott.sh > /dev/null 2>&1
```

---

### 6. Configuración de Reproductores Cliente

Las listas incluyen directivas estándar `#KODIPROP` con la clave ClearKey (`KID:KEY`):

```m3u
#EXTINF:-1 tvg-name="DAZN 1" group-title="Deportes",DAZN 1
#KODIPROP:inputstreamaddon=inputstream.adaptive
#KODIPROP:inputstream.adaptive.manifest_type=mpd
#KODIPROP:inputstream.adaptive.license_type=clearkey
#KODIPROP:inputstream.adaptive.license_key=3da197d13d754505887a04aedd17922e:0028b47ca60594991910c6f6048c51a0
https://ejemplo-cdn.net/manifest.mpd
```

#### 📱 TiviMate (Android TV / FireStick):
1. **Ajustes** → **Listas de reproducción** → **Añadir lista** → **Lista M3U**.
2. Introduce la URL de tu lista (ej. `http://TU_IP/deportes.m3u`).
3. En **Frecuencia de actualización**, selecciona **Cada 2 o 4 horas**.
4. TiviMate leerá automáticamente las etiquetas ClearKey y reproducirá los canales sin configuración adicional.

#### 📱 OTT Navigator:
1. **Configuración** → **Proveedor** → **Añadir lista M3U**.
2. Pega la URL del servidor (`http://TU_IP/deportes.m3u`).
3. Asegúrate de que en **Motor de reproducción / Códec** esté seleccionado **ExoPlayer** (soporte nativo de ClearKey).

#### 💻 Kodi (PC, Mac, Android):
1. Activa el addon **InputStream Adaptive** en *Videoplayer InputStream*.
2. Configura **PVR IPTV Simple Client** con la URL remota de la lista M3U.
3. Kodi descifrará los flujos MPD protegidos de forma nativa.

---

## 🐳 Despliegue con Docker

```bash
docker compose up -d
```
Las listas generadas se almacenarán automáticamente en la carpeta mapeada `./output/`.

---

## 📄 Licencia

Distribuido bajo la licencia MIT. Consulta el archivo `LICENSE` para más información.
