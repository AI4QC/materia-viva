import { describe, expect, it } from 'vitest'

import { curveTraces } from './SpectraPanel'

describe('curveTraces', () => {
  it('keeps every valid component series in the plotted data', () => {
    const traces = curveTraces({
      x: [0, 1], y: [2, 3], y_label: 'Total',
      series: [{ name: 'Ag', y: [1, 2] }, { name: 'Cl', y: [1, 1] }],
    })

    expect(traces.map(({ name, y }) => ({ name, y }))).toEqual([
      { name: 'Total', y: [2, 3] },
      { name: 'Ag', y: [1, 2] },
      { name: 'Cl', y: [1, 1] },
    ])
  })
})
