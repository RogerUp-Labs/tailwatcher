import { sdk } from './sdk'

/** NTFY must be running so alerts have somewhere to go. */
export const setDependencies = sdk.setupDependencies(async () => ({
  ntfy: {
    kind: 'running',
    versionRange: '*',
    healthChecks: [],
  },
}))
