import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CrystalViewer } from './CrystalViewer'

const structure = {
  formula: 'SiO2',
  site_count: 3,
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

describe('CrystalViewer', () => {
  it('uses the OVITO render as the primary crystal view and updates the camera', () => {
    render(<CrystalViewer materialId="exp-000001" structure={structure} />)

    const image = screen.getByRole('img', { name: 'SiO2 的 OVITO 晶体结构渲染' })
    expect(image).toHaveAttribute('src', expect.stringContaining('/api/materials/exp-000001/render?'))
    expect(image).toHaveAttribute('src', expect.stringContaining('view=isometric'))

    fireEvent.click(screen.getByRole('button', { name: '顶视图' }))
    expect(screen.getByRole('img', { name: 'SiO2 的 OVITO 晶体结构渲染' })).toHaveAttribute('src', expect.stringContaining('view=top'))
  })

  it('offers an interactive fallback without loading WebGL', () => {
    render(<CrystalViewer materialId="pool-000001" structure={structure} />)

    fireEvent.click(screen.getByRole('tab', { name: '交互式 3D' }))
    expect(screen.getByText('当前浏览器无法启动 WebGL')).toBeInTheDocument()
  })
})
