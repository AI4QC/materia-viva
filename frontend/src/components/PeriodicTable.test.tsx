import { useState } from 'react'
import { fireEvent, render, screen } from '../test/render'
import { describe, expect, it } from 'vitest'

import { PeriodicTable, type ElementSelection } from './PeriodicTable'


function Harness() {
  const [selection, setSelection] = useState<ElementSelection>({})
  return <PeriodicTable selection={selection} onChange={setSelection} />
}


describe('PeriodicTable', () => {
  it('renders all 118 elements as accessible controls', () => {
    render(<Harness />)

    expect(screen.getAllByRole('button')).toHaveLength(118)
    expect(screen.getByRole('button', { name: /Hydrogen \(H\)/ })).toBeVisible()
  })

  it('cycles neutral to include to exclude and back to neutral', () => {
    render(<Harness />)
    const lithium = screen.getByRole('button', { name: /Lithium \(Li\)/ })

    expect(lithium).toHaveAttribute('data-state', 'neutral')
    fireEvent.click(lithium)
    expect(lithium).toHaveAttribute('data-state', 'include')
    fireEvent.click(lithium)
    expect(lithium).toHaveAttribute('data-state', 'exclude')
    fireEvent.click(lithium)
    expect(lithium).toHaveAttribute('data-state', 'neutral')
  })
})
