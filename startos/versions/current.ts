import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.18.0:0',
  releaseNotes: {
    en_US:
      'Import a trip: tap Import next to + Add trip and paste your booking confirmation, or choose a saved email (.eml) or calendar file (.ics). TailWatcher finds the flights, connections and flight home and fills in the Add trip form for you to check before adding. It reads the flight details airlines and booking sites hide in confirmation emails, calendar events from Add to calendar, TripIt or Kayak, and plain text. PDFs and screenshots can\'t be read yet: copy their text and paste it instead. Reading a confirmation uses none of your AeroDataBox requests.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
