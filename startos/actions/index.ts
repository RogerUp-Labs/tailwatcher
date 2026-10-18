import { sdk } from '../sdk'
import { configure } from './configure'
import { testNotification } from './testNotification'

export const actions = sdk.Actions.of()
  .addAction(configure)
  .addAction(testNotification)
