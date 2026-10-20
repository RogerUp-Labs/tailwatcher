FROM python:3.12-alpine AS airports
WORKDIR /build
COPY app/trim_airports.py .
RUN wget -q -O airports-full.csv https://davidmegginson.github.io/ourairports-data/airports.csv \
 && wget -q -O airports-tz.json https://raw.githubusercontent.com/mwgg/Airports/master/airports.json \
 && python trim_airports.py airports-full.csv airports.csv airports-tz.json

FROM python:3.12-alpine
WORKDIR /app
COPY --from=airports /build/airports.csv /app/airports.csv
COPY app/tailwatcher.py app/commands.py app/flights.py app/lookup.py app/trips.py app/history.py app/web.py app/edits.py app/ntfy_admin.py app/invites.py app/itinerary.py /app/
COPY app/web/ /app/web/
COPY icon.svg /app/web/icon.svg
COPY instructions.md /app/web/guide.md
# One image for both: StartOS's main.ts sets TW_PLATFORM=startos, and a plain
# Docker install (docker/docker-compose.yml) keeps this default.
ENV PYTHONUNBUFFERED=1 TW_PLATFORM=docker
LABEL org.opencontainers.image.source="https://github.com/RogerUp-Labs/tailwatcher" \
      org.opencontainers.image.description="Push alerts when a watched plane or flight takes off or lands" \
      org.opencontainers.image.licenses="MIT"
RUN mkdir -p /data
VOLUME /data
EXPOSE 8080
# /health stays open even with the dashboard password on.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/health || exit 1
CMD ["python", "/app/tailwatcher.py"]
