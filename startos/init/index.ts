import { sdk } from '../sdk'
import { actions } from '../actions'
import { configure } from '../actions/configure'
import { restoreInit } from '../backups'
import { setDependencies } from '../dependencies'
import { configJson } from '../fileModels/config.json'
import { setInterfaces } from '../interfaces'
import { versionGraph } from '../versions'

/** On a fresh install, ask the user to add tail numbers and the NTFY token. */
const configureTask = sdk.setupOnInit(async (effects, kind) => {
  if (kind !== 'install') return
  if ((await configJson.read().once())?.aircraft.length) return
  await sdk.action.createOwnTask(effects, configure, 'critical', {
    reason: 'Add the tail numbers to watch and your NTFY publisher token.',
  })
})

export const init = sdk.setupInit(
  restoreInit,
  versionGraph,
  setInterfaces,
  setDependencies,
  actions,
  configureTask,
)

export const uninit = sdk.setupUninit(versionGraph)
