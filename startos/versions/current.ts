import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.22.0:0',
  releaseNotes: {
    en_US:
      'Family accounts: give each person their own login to the Web UI, so they see only their own watchers and trips (trips are the private part). People can still share a trip with each other: it shows up read-only under "Shared with me" on their dashboard, with where the flight and the plane flying in for it are, and "Stop following" takes them off it. Admins add people and move watchers between them on the new People page, and only admins see Settings; they never see anyone else\'s trips. Turn it on in Settings → Signing in to this page (new installs choose at first setup); nothing changes until you do. Also new: each watcher can have their own time zone for alerts, replies and "until fri", and shared-trip alerts arrive in the recipient\'s time zone. Signing in now uses a sign-in page instead of the browser\'s password prompt. A locked-out admin uses Actions → Reset Web UI Password.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
