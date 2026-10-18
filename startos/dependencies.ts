import { configJson } from './fileModels/config.json'
import { sdk } from './sdk'

/** NTFY is only a dependency when alerts go through this server's NTFY. */
export const setDependencies = sdk.setupDependencies(async ({ effects }) => {
  const server = await configJson.read((c) => c.ntfyServer).const(effects)
  if (server !== 'local') return {}
  return {
    ntfy: {
      kind: 'running',
      versionRange: '*',
      healthChecks: [],
    },
  }
})
