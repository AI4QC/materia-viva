import { render as rtlRender, type RenderOptions } from '@testing-library/react'
import type { ReactElement } from 'react'

import { I18nProvider, type Language } from '../i18n'

interface Options extends Omit<RenderOptions, 'wrapper'> {
  /** Components read copy through the i18n context, so tests need a provider. */
  lang?: Language
}

export function render(ui: ReactElement, { lang = 'en', ...options }: Options = {}) {
  return rtlRender(ui, {
    wrapper: ({ children }) => <I18nProvider initial={lang}>{children}</I18nProvider>,
    ...options,
  })
}

export * from '@testing-library/react'
