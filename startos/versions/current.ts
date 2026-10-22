import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.22.1:0',
  releaseNotes: {
    en_US:
      'Shorter Activity list on phones: the Web UI (and the home screen app) now shows the 8 newest entries, with "Show more" to load more and "Show less" to fold it back, so Activity no longer takes over the page. Computers keep the scrolling list as before.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
