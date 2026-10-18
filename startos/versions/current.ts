import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.3.0:0',
  releaseNotes: {
    en_US:
      'Text commands: type in your NTFY topic to manage your list. Send a tail number to add it ("N12345" or "add N12345 Vegas trip"), "remove N12345" to drop it, and "list" to see what you watch and what is airborne. Settings changes now apply without restarting the service. To use text commands, grant pkg_tailwatcher Read-Write on tailwatcher* in NTFY, and each watcher Read-Write on their topic.',
  },
  migrations: {
    // textCommands defaults to on via the schema; nothing to rewrite.
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
