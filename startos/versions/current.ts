import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.15.0:0',
  releaseNotes: {
    en_US:
      'Invite links: Connect phone can create a normal web link to text, iMessage or Signal to someone anywhere. It opens a simple page that walks them through installing ntfy and subscribing in two taps. Invites expire after the days you choose (7 by default) and can be cancelled from the dashboard. They use TailWatcher\'s public address (for example StartTunnel) and show only that one person\'s subscribe details.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
