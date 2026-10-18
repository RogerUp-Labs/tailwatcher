FROM python:3.12-alpine AS airports
WORKDIR /build
COPY app/trim_airports.py .
RUN wget -q -O airports-full.csv https://davidmegginson.github.io/ourairports-data/airports.csv \
 && python trim_airports.py airports-full.csv airports.csv

FROM python:3.12-alpine
WORKDIR /app
COPY --from=airports /build/airports.csv /app/airports.csv
COPY app/tailwatcher.py app/commands.py app/flights.py app/lookup.py app/trips.py app/history.py app/web.py app/edits.py /app/
COPY app/web/ /app/web/
COPY icon.svg /app/web/icon.svg
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "/app/tailwatcher.py"]
