import { sdk } from './sdk'
import { webPort } from './utils'

/** The read-only dashboard: trips, watchers, activity and status. */
export const setInterfaces = sdk.setupInterfaces(async ({ effects }) => {
  const uiMulti = sdk.MultiHost.of(effects, 'ui-multi')
  const uiOrigin = await uiMulti.bindPort(webPort, { protocol: 'http' })
  const ui = sdk.createInterface(effects, {
    name: 'Web UI',
    id: 'ui',
    description:
      'Dashboard of trips, watched aircraft and recent alerts. Log in with any username and the password from "Show Web UI Password".',
    type: 'ui',
    masked: false,
    schemeOverride: null,
    username: null,
    path: '',
    query: {},
  })
  return [await uiOrigin.export([ui])]
})
