import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.17.0:0',
  releaseNotes: {
    en_US:
      'Connecting flights and stops: add a connection with then (inbound UA1234 then UA567), connect 1 UA567, or the new Connecting flight row on + Add trip. The flights are listed, shared and cancelled together like a round trip. On the day, TailWatcher follows your first flight and tells you how many minutes you will have to make the next one, warns when that gets tight, and tells you when you land. With AeroDataBox it also warns ahead of time when the scheduled connection is tight. Flights with a stop under one flight number now work too: say from or to the stop if you board or get off there, the plane coming in is found correctly, and family only gets the landing alert at your real destination.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
