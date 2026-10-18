import { sdk } from '../sdk'
import { configure } from './configure'
import { resetPassword, showPassword } from './showPassword'
import { testNotification } from './testNotification'

export const actions = sdk.Actions.of()
  .addAction(configure)
  .addAction(testNotification)
  .addAction(showPassword)
  .addAction(resetPassword)
