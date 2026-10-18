import { sdk } from '../sdk'
import { actions } from '../actions'
import { configure } from '../actions/configure'
import { restoreInit } from '../backups'
import { setDependencies } from '../dependencies'
import { configJson } from '../fileModels/config.json'
import { newPassword, webuiJson } from '../fileModels/webui.json'
import { setInterfaces } from '../interfaces'
import { versionGraph } from '../versions'

/** On a fresh install, ask the user to add tail numbers and the NTFY token. */
const configureTask = sdk.setupOnInit(async (effects, kind) => {
  if (kind !== 'install') return
  if ((await configJson.read().once())?.watchers.length) return
  await sdk.action.createOwnTask(effects, configure, 'critical', {
    reason:
      'Add a watcher with the tail numbers to watch, and your NTFY publisher token.',
  })
})

/** Every install (and update from before the Web UI) gets a dashboard password. */
const webPassword = sdk.setupOnInit(async (effects) => {
  if ((await webuiJson.read().once())?.password) return
  await webuiJson.write(effects, { password: newPassword() })
})

export const init = sdk.setupInit(
  restoreInit,
  versionGraph,
  setInterfaces,
  setDependencies,
  actions,
  configureTask,
  webPassword,
)

export const uninit = sdk.setupUninit(versionGraph)
