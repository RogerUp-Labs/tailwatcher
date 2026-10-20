import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.20.3:0',
  releaseNotes: {
    en_US:
      'Easier Add trip form: the return flight is tucked under a "Return flight" section you open when you need it, and connecting flights are added one at a time with "+ Add connection" (and "+ Add return connection"), as many as your trip has, up to 8 flights each way. Import fills in every connection it finds, and Edit can add several at once.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
