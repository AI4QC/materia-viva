import { render, screen } from '../test/render'
import { describe, expect, it } from 'vitest'

import { InteractiveCrystal } from './InteractiveCrystal'

const structure = {
  formula: 'SiO2',
  site_count: 1,
  lattice: {
    matrix: [[5, 0, 0], [0, 5, 0], [0, 0, 5]],
    a: 5,
    b: 5,
    c: 5,
    alpha: 90,
    beta: 90,
    gamma: 90,
    volume: 125,
  },
  sites: [
    { index: 0, element: 'Si', species: 'Si', occupancy: 1, atomic_number: 14, fractional: [0, 0, 0], cartesian: [0, 0, 0], color: [0.94, 0.78, 0.63], radius: 1.11 },
  ],
  bonds: [],
}

describe('InteractiveCrystal', () => {
  it('offers an OVITO fallback without requiring WebGL', () => {
    render(<InteractiveCrystal structure={structure} showCell representation="ball_stick" />)

    expect(screen.getByText('This browser cannot start WebGL')).toBeInTheDocument()
    expect(screen.getByText('You can still browse the structure with the OVITO render above.')).toBeInTheDocument()
  })
})
