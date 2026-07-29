import { fireEvent, render, screen, waitFor } from './test/render'
import { beforeEach, expect, test, vi } from 'vitest'

import App from './App'

vi.mock('./hooks/useMaterials', () => ({
  useAtlasStats: () => ({
    total: 8_225_138,
    datasets: { experimental: 99_162, candidate: 8_125_976 },
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

  expect(screen.getByRole('link', { name: 'MateriaViva home' })).toBeInTheDocument()
  expect(screen.getAllByText('MateriaViva').length).toBeGreaterThan(0)
  expect(screen.getAllByText('MateriaViva').length).toBeGreaterThan(0)
  expect(screen.getByRole('heading', {
    name: /Every crystal dataset in one place,\s*discover 8\.22 million unique structures\./,
  })).toBeInTheDocument()
  expect(screen.getByText(/Unified and deduplicated across sources/)).toBeInTheDocument()
  expect(screen.queryByText(/CSAgent/i)).not.toBeInTheDocument()
  expect(screen.queryByText(/Materials Atlas/i)).not.toBeInTheDocument()
})

test('switches from the night theme to the day theme and remembers it', async () => {
  render(<App />)

  fireEvent.click(screen.getByRole('button', { name: 'Switch to light mode' }))

  await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'light'))
  expect(window.localStorage.getItem('mv-theme')).toBe('light')
  expect(screen.getByRole('button', { name: 'Switch to dark mode' })).toBeInTheDocument()
})

test('starts in English and switches the interface to Chinese on request', async () => {
  render(<App />)

  expect(screen.getByRole('heading', {
    name: /Every crystal dataset in one place,/,
  })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: '切换到中文' }))

  await waitFor(() => expect(screen.getByRole('heading', {
    name: /汇聚全部晶体数据集，/,
  })).toBeInTheDocument())
  expect(window.localStorage.getItem('mv-lang')).toBe('zh')
  expect(document.documentElement).toHaveAttribute('lang', 'zh-CN')
  expect(screen.getByRole('button', { name: 'Switch to English' })).toBeInTheDocument()
})

test('restores the stored day theme on the next visit', async () => {
  window.localStorage.setItem('mv-theme', 'light')

  render(<App />)

  await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'light'))
  expect(screen.getByRole('button', { name: 'Switch to dark mode' })).toBeInTheDocument()
})
