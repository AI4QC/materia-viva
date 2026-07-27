import { render, screen } from '@testing-library/react'
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

    expect(screen.getByText('当前浏览器无法启动 WebGL')).toBeInTheDocument()
    expect(screen.getByText('仍可使用上方 OVITO 高质量渲染浏览结构。')).toBeInTheDocument()
  })
})
