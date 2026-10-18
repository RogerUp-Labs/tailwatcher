import { newPassword, webuiJson } from '../fileModels/webui.json'
import { sdk } from '../sdk'

export const showPassword = sdk.Action.withoutInput(
  'show-web-password',

  async () => ({
    name: 'Show Web UI Password',
    description:
      'The dashboard password, used only when "Require Web UI Password" is on in Configure. Your browser asks for a username too; anything works.',
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
      message: 'Use any username with this password.',
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
    description: 'Make a new dashboard password. The old one stops working right away.',
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
      message: 'Use any username with this password.',
      result: { type: 'single', value: password, masked: true, copyable: true, qr: false },
    }
  },
)
