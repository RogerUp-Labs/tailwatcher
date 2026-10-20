import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_20_2 = VersionInfo.of({
  version: '0.20.2:0',
  releaseNotes: {
    en_US:
      'Help is now a full page instead of a small pop-up: a list of topics down the side (under Contents on a phone), search, and an Open in new tab link. The browser\'s Back button closes it, and a Help address like …/#help/importing-a-trip opens straight to that topic, so you can bookmark or send it.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
