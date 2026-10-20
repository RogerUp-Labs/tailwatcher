import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_19_0 = VersionInfo.of({
  version: '0.19.0:0',
  releaseNotes: {
    en_US:
      'TailWatcher can now also run without a Start9, as an ordinary Docker container on a Synology, Unraid or TrueNAS NAS or any computer with Docker, with alerts through ntfy.sh or an ntfy server you run yourself. See Running without a Start9 in the instructions. Nothing changes on StartOS, apart from a few hints that now point at Settings in the Web UI.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
