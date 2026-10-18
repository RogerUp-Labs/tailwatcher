import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.8.1:0',
  releaseNotes: {
    en_US:
      'The Web UI no longer asks for a password by default: it is a household admin panel showing everyone\'s watchers and trips, reachable on your network and VPN. Turn on "Require Web UI Password" in Configure if you want one.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
