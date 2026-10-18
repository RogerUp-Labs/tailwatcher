import { FileHelper, utils, z } from '@start9labs/start-sdk'
import { sdk } from '../sdk'

/** The Web UI password, read by app/web.py (HTTP Basic auth, any username). */
export const webuiJson = FileHelper.json(
  { base: sdk.volumes.main, subpath: 'webui.json' },
  z.object({ password: z.string().catch('') }),
)

export const newPassword = () =>
  utils.getDefaultString({ charset: 'a-k,m-z,A-H,J-N,P-Z,2-9', len: 20 })
