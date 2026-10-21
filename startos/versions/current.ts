import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.20.5:0',
  releaseNotes: {
    en_US:
      'Connect phone links and invite links now give the subscription a friendly name in the ntfy Android app, like "TailWatcher · Dad", instead of the long random topic. It applies when someone subscribes; anyone already subscribed can rename it in the ntfy app (Subscription settings → Display name). The iPhone ntfy app has no display names, so there it still shows the server and topic; Help and the invite page now say so.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
