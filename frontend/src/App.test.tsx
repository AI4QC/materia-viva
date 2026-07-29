import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'

import App from './App'

vi.mock('./hooks/useMaterials', () => ({
  useAtlasStats: () => ({
    total: 6_219_302,
    datasets: { experimental: 99_162, candidate: 6_120_140 },
    property_counts: {},
    ovito_available: true,
  }),
  useMaterials: () => ({
    data: {
      items: [], total: 6_219_302, page: 1, page_size: 24, pages: 259_138,
      facets: { datasets: { experimental: 99_162, candidate: 6_120_140 } },
    },
    error: null,
    loading: false,
    refresh: vi.fn(),
  }),
}))

beforeEach(() => {
  window.localStorage.clear()
  delete document.documentElement.dataset.theme
})

test('presents the database as MateriaViva with a unified deduplicated-data promise', () => {
  render(<App />)

  expect(screen.getByRole('link', { name: 'MateriaViva 首页' })).toBeInTheDocument()
  expect(screen.getAllByText('MateriaViva').length).toBeGreaterThan(0)
  expect(screen.getAllByText('MateriaViva').length).toBeGreaterThan(0)
  expect(screen.getByRole('heading', {
    name: /汇聚全部晶体数据集，\s*发现 822 万种独特结构。/,
  })).toBeInTheDocument()
  expect(screen.getByText(/跨数据源统一整合与去重/)).toBeInTheDocument()
  expect(screen.queryByText(/CSAgent/i)).not.toBeInTheDocument()
  expect(screen.queryByText(/Materials Atlas/i)).not.toBeInTheDocument()
})

test('switches from the night theme to the day theme and remembers it', async () => {
  render(<App />)

  fireEvent.click(screen.getByRole('button', { name: '切换到日间模式' }))

  await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'light'))
  expect(window.localStorage.getItem('mv-theme')).toBe('light')
  expect(screen.getByRole('button', { name: '切换到夜间模式' })).toBeInTheDocument()
})

test('restores the stored day theme on the next visit', async () => {
  window.localStorage.setItem('mv-theme', 'light')

  render(<App />)

  await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'light'))
  expect(screen.getByRole('button', { name: '切换到夜间模式' })).toBeInTheDocument()
})
