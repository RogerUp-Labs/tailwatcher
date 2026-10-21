import { setupManifest } from '@start9labs/start-sdk'
import { installAlert, long, short } from './i18n'

export const manifest = setupManifest({
  id: 'tailwatcher',
  title: 'TailWatcher',
  license: 'MIT',
  packageRepo: 'https://github.com/RogerUp-Labs/tailwatcher',
  upstreamRepo: 'https://github.com/RogerUp-Labs/tailwatcher',
  marketingUrl: 'https://github.com/RogerUp-Labs/tailwatcher',
  donationUrl: null,
  description: { short, long },
  volumes: ['main'],
  images: {
    main: {
      // Built locally by `make` (docker build), so no buildx is needed.
      source: { dockerTag: 'start9/tailwatcher/main:0.21.0' },
      arch: ['x86_64', 'aarch64'],
    },
  },
  alerts: {
    install: installAlert,
    update: null,
    uninstall: null,
    restore: null,
    start: null,
    stop: null,
  },
  dependencies: {
    ntfy: {
      description:
        "Optional. By default TailWatcher sends alerts through the public ntfy.sh service. Choose this server's NTFY in Configure to keep alerts on your own hardware.",
      optional: true,
      // start-cli copies NTFY's title and icon from its official package at
      // pack time, so the Dependencies section shows them.
      s9pk: 'https://github.com/Start9Labs/ntfy-startos/releases/download/v2.31.1_0/ntfy_x86_64.s9pk',
    },
  },
})
