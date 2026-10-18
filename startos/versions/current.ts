import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.5.1:0',
  releaseNotes: {
    en_US:
      'Corrected NTFY setup: NTFY does not let a Provision Publisher account be given read access, so text commands need a regular NTFY user instead. Create User "tailwatcher", grant it Read-Write on "tailwatcher*", create an access token for it in the NTFY web UI (Account → Access tokens), and paste that token into Configure. The install message, Configure help and health messages now say this.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
