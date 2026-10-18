import { sdk } from './sdk'

/** Headless: TailWatcher has no web UI, it only publishes to NTFY. */
export const setInterfaces = sdk.setupInterfaces(async () => [])
