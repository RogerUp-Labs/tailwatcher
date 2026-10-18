import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_5_0 = VersionInfo.of({
  version: '0.5.0:0',
  releaseNotes: {
    en_US:
      'Aircraft lookup: text "info N12345" (or "who N12345", "info UA1234") to your topic to see what the plane is, who owns it (FAA registry for US aircraft: owner, city and state, model, year, engine, registration status), where it is right now, any military or privacy flags, and a photo from planespotters.net. Uses hexdb.io for non-US aircraft. No settings change.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
