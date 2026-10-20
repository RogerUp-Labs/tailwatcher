import { VersionGraph } from '@start9labs/start-sdk'
import { current } from './current'
import { v0_1_0 } from './v0.1.0'
import { v0_2_0 } from './v0.2.0'
import { v0_3_0 } from './v0.3.0'
import { v0_4_0 } from './v0.4.0'
import { v0_5_0 } from './v0.5.0'
import { v0_5_1 } from './v0.5.1'
import { v0_6_0 } from './v0.6.0'
import { v0_6_1 } from './v0.6.1'
import { v0_7_0 } from './v0.7.0'
import { v0_8_0 } from './v0.8.0'
import { v0_8_1 } from './v0.8.1'
import { v0_8_2 } from './v0.8.2'
import { v0_9_0 } from './v0.9.0'
import { v0_10_0 } from './v0.10.0'
import { v0_11_0 } from './v0.11.0'
import { v0_12_0 } from './v0.12.0'
import { v0_13_0 } from './v0.13.0'
import { v0_14_0 } from './v0.14.0'
import { v0_15_0 } from './v0.15.0'
import { v0_16_0 } from './v0.16.0'
import { v0_16_1 } from './v0.16.1'
import { v0_16_2 } from './v0.16.2'

export const versionGraph = VersionGraph.of({
  current,
  other: [v0_16_2, v0_16_1, v0_16_0, v0_15_0, v0_14_0, v0_13_0, v0_12_0, v0_11_0, v0_10_0, v0_9_0, v0_8_2, v0_8_1, v0_8_0, v0_7_0, v0_6_1, v0_6_0, v0_5_1, v0_5_0, v0_4_0, v0_3_0, v0_2_0, v0_1_0],
})
