import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.6.1:0',
  releaseNotes: {
    en_US:
      'Trips added well ahead ("inbound AA1234 11/14") now stay until their date even before AeroDataBox has a schedule for them, and are checked once a day until two days out instead of every 6 hours, to save your free AeroDataBox requests.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
