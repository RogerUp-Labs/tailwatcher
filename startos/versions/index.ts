import { VersionGraph } from '@start9labs/start-sdk'
import { current } from './current'
import { v0_1_0 } from './v0.1.0'
import { v0_2_0 } from './v0.2.0'

export const versionGraph = VersionGraph.of({
  current,
  other: [v0_2_0, v0_1_0],
})
