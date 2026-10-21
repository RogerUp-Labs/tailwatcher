import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_20_4 = VersionInfo.of({
  version: '0.20.4:0',
  releaseNotes: {
    en_US:
      'Help now explains the "Trust anchor for certification path not found" error some phones get in the ntfy app with this server\'s NTFY: a Start9 signs its addresses, including a StartTunnel public IP, with its own root certificate, which phones only trust once it is installed. The fix for people outside your household is a public domain with a Let\'s Encrypt certificate through StartTunnel; for your own phones, installing the root certificate also works. Connect phone and invite pages now point to these steps, and once NTFY or TailWatcher has a public domain, Connect phone links and invites use it instead of a public IP.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
