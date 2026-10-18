import { sdk } from './sdk'
import { webPort } from './utils'

/** The dashboard (an admin panel for the whole household): trips, watchers, activity and status. */
export const setInterfaces = sdk.setupInterfaces(async ({ effects }) => {
  const uiMulti = sdk.MultiHost.of(effects, 'ui-multi')
  const uiOrigin = await uiMulti.bindPort(webPort, { protocol: 'http' })
  const ui = sdk.createInterface(effects, {
    name: 'Web UI',
    id: 'ui',
    description:
      'Dashboard of every watcher, their aircraft and trips, and recent alerts. Opens without a login unless "Require Web UI Password" is on in Configure.',
    type: 'ui',
    masked: false,
    schemeOverride: null,
    username: null,
    path: '',
    query: {},
  })
  return [await uiOrigin.export([ui])]
})
