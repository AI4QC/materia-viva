import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { SearchResponse } from '../api/client'
import { MaterialResults } from './MaterialResults'


const response: SearchResponse = {
  items: [
    {
      material_id: 'exp-train-1',
      formula: 'LiFePO4',
      chemical_system: 'Fe-Li-O-P',
      dataset: 'experimental',
      is_experimental: true,
      n_elements: 4,
      n_atoms: 7,
      pbes_gap: 2.1,
      density: 3.6,
      spacegroup_number: 62,
      crystal_system: 'orthorhombic',
    },
  ],
  total: 25,
  page: 1,
  page_size: 24,
  pages: 2,
  facets: { datasets: { experimental: 25 } },
}


describe('MaterialResults', () => {
  it('exposes loading, empty, and error states', () => {
    const common = { onPage: vi.fn(), onSelect: vi.fn(), onRetry: vi.fn() }
    const { rerender } = render(<MaterialResults {...common} loading data={null} error={null} />)
    expect(screen.getByRole('status')).toHaveTextContent('正在检索材料空间')

    rerender(<MaterialResults {...common} loading={false} data={{ ...response, items: [], total: 0, pages: 0 }} error={null} />)
    expect(screen.getByText('没有命中结构')).toBeVisible()

    rerender(<MaterialResults {...common} loading={false} data={null} error="索引不可用" />)
    expect(screen.getByRole('alert')).toHaveTextContent('索引不可用')
    fireEvent.click(screen.getByRole('button', { name: '重新尝试' }))
    expect(common.onRetry).toHaveBeenCalledOnce()
  })

  it('opens a result and advances pagination', () => {
    const onPage = vi.fn()
    const onSelect = vi.fn()
    render(
      <MaterialResults
        loading={false}
        data={response}
        error={null}
        onPage={onPage}
        onSelect={onSelect}
        onRetry={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /查看 LiFePO4/ }))
    expect(onSelect).toHaveBeenCalledWith('exp-train-1')
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(onPage).toHaveBeenCalledWith(2)
  })
})
