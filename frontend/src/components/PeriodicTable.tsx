import { useState } from 'react'

import { ELEMENTS } from '../data/elements'
import { useI18n } from '../i18n'

export type ElementState = 'neutral' | 'include' | 'exclude'
export type ElementSelection = Partial<Record<string, Exclude<ElementState, 'neutral'>>>

interface PeriodicTableProps {
  selection: ElementSelection
  onChange: (selection: ElementSelection) => void
}

export function PeriodicTable({ selection, onChange }: PeriodicTableProps) {
  const { t } = useI18n()
  const [action, setAction] = useState<Exclude<ElementState, 'neutral'>>('include')
  const toggle = (symbol: string) => {
    const current = selection[symbol] ?? 'neutral'
    const updated = { ...selection }
    if (current === action) delete updated[symbol]
    else updated[symbol] = action
    onChange(updated)
  }

  return (
    <div className="periodic-table" aria-label={t('lab.elementFilter')}>
      <div className="element-action" aria-label={t('lab.actionLabel')}>
        <span>{t('lab.actionLabel')}</span>
        <button aria-pressed={action === 'include'} onClick={() => setAction('include')} type="button">+ {t('legend.include')}</button>
        <button aria-pressed={action === 'exclude'} onClick={() => setAction('exclude')} type="button">− {t('legend.exclude')}</button>
        <small>{t('lab.actionHint')}</small>
      </div>
      <div className="periodic-table__grid">
        {ELEMENTS.map((element) => {
          const state = selection[element.symbol] ?? 'neutral'
          return (
            <button
              className={`element element--${element.category}`}
              data-state={state}
              key={element.number}
              onClick={() => toggle(element.symbol)}
              style={{ gridColumn: element.group, gridRow: element.period }}
              type="button"
              aria-label={`${element.name} (${element.symbol}): ${state}`}
              aria-pressed={state === 'exclude' ? 'mixed' : state === 'include'}
              title={`${element.number} · ${element.name}`}
            >
              <span className="element__number">{element.number}</span>
              <span className="element__symbol">{element.symbol}</span>
              <span className="element__state" aria-hidden="true">
                {state === 'include' ? '+' : state === 'exclude' ? '−' : ''}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
