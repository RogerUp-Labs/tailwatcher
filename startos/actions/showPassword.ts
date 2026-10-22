import { newPassword, webuiJson } from '../fileModels/webui.json'
import { sdk } from '../sdk'

export const showPassword = sdk.Action.withoutInput(
  'show-web-password',

  async () => ({
    name: 'Show Web UI Password',
    description:
      'The dashboard password, used when Web UI sign-in is "One shared password". With family accounts it is only the first admin\'s password if they never changed it; use Reset Web UI Password if the admin is locked out.',
    warning: null,
    allowedStatuses: 'any',
    group: 'Web UI',
    visibility: 'enabled',
  }),

  async ({ effects }) => {
    let password = (await webuiJson.read().once())?.password
    if (!password) {
      password = newPassword()
      await webuiJson.write(effects, { password })
    }
    return {
      version: '1',
      title: 'Web UI Password',
      message: 'Sign in to the Web UI with this password.',
      result: {
        type: 'single',
        value: password,
        masked: true,
        copyable: true,
        qr: false,
      },
    }
  },
)

export const resetPassword = sdk.Action.withoutInput(
  'reset-web-password',

  async () => ({
    name: 'Reset Web UI Password',
    description:
      'Make a new dashboard password. The old one stops working right away. With family accounts, it becomes the first admin\'s new password (for when they are locked out).',
    warning: 'Anyone using the old password will be asked for the new one.',
    allowedStatuses: 'any',
    group: 'Web UI',
    visibility: 'enabled',
  }),

  async ({ effects }) => {
    const password = newPassword()
    await webuiJson.write(effects, { password })
    return {
      version: '1',
      title: 'New Web UI Password',
      message:
        'Sign in with this password. With family accounts, it is now the first admin\'s password: sign in with their username, then change it under My account.',
      result: { type: 'single', value: password, masked: true, copyable: true, qr: false },
    }
  },
)
