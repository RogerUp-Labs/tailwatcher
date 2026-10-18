import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.7.0:0',
  releaseNotes: {
    en_US:
      'Manage trips by text: "trips" numbers them soonest first, "change 1 AA5678" (or a new time, date, plane or airport) updates one, and "cancel 1" removes it. If the airline renumbers or cancels a flight, TailWatcher notices on its next AeroDataBox check, tells you, and suggests the likely new flight number (same airline, airport and destination, near the old time) for you to confirm with "change". AeroDataBox checks now scale with distance: weekly more than 2 weeks out, daily until the last day, then the full plane checks, about 20 requests for a trip added a month ahead. Planes are only followed on ADS-B in the last day before departure.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
