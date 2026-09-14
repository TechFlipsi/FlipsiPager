# ═══════════════════════════════════════════════════════════════════
#  Feuerwehr-Einsatz-Monitor — Docker-Image
#  Build:   docker build -t feuerwehr-monitor .
#  Run:     siehe docker-compose.yml oder README (Docker-Sektion)
# ═══════════════════════════════════════════════════════════════════
FROM python:3.13-slim

# tzdata: damit Europe/Vienna-Zeiten im Container stimmen
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# pyproj ist optional (Pegel-Koordinaten-Umwandlung) — im Code try/except-gesichert,
# aber mit dabei, damit /pegel und /umkreis voll funktionieren.
RUN pip install --no-cache-dir pyproj

# Non-root Nützer mit festem HOME=/data → ALLE Bot-Dateien landen unter
# /data/.config/fw_bot/ (Config, Token, users.json, State) → nur /data mounten.
RUN useradd --create-home --home-dir /data --shell /usr/sbin/nologin fwbot \
    && mkdir -p /data/.config/fw_bot \
    && chown -R fwbot:fwbot /data

WORKDIR /app
COPY einsatz_watcher_v4.py /app/einsatz_watcher_v4.py
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod 700 /app/einsatz_watcher_v4.py /app/docker-entrypoint.sh \
    && chown fwbot:fwbot /app/einsatz_watcher_v4.py /app/docker-entrypoint.sh

VOLUME /data
USER fwbot
ENV HOME=/data

ENTRYPOINT ["/app/docker-entrypoint.sh"]