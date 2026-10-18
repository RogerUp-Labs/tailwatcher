import { setupManifest } from '@start9labs/start-sdk'
import { installAlert, long, short } from './i18n'

export const manifest = setupManifest({
  id: 'tailwatcher',
  title: 'TailWatcher',
  license: 'MIT',
  packageRepo: 'https://github.com/homebrew-gh/tailwatcher',
  upstreamRepo: 'https://github.com/homebrew-gh/tailwatcher',
  marketingUrl: 'https://github.com/homebrew-gh/tailwatcher',
  donationUrl: null,
  description: { short, long },
  volumes: ['main'],
  images: {
    main: {
      // Built locally by `make` (docker build), so no buildx is needed.
      source: { dockerTag: 'start9/tailwatcher/main:0.8.2' },
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
        'TailWatcher publishes its takeoff and landing alerts to a topic on this NTFY server, which pushes them to the NTFY app on your phone.',
      optional: false,
      // start-cli copies NTFY's title and icon from its official package at
      // pack time, so the Dependencies section shows them.
      s9pk: 'https://github.com/Start9Labs/ntfy-startos/releases/download/v2.31.1_0/ntfy_x86_64.s9pk',
    },
  },
})
