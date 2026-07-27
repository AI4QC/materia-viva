import { ELEMENTS } from '../data/elements'

export type ElementState = 'neutral' | 'include' | 'exclude'
export type ElementSelection = Partial<Record<string, Exclude<ElementState, 'neutral'>>>

interface PeriodicTableProps {
  selection: ElementSelection
  onChange: (selection: ElementSelection) => void
}

const nextState: Record<ElementState, ElementState> = {
  neutral: 'include',
  include: 'exclude',
  exclude: 'neutral',
}

export function PeriodicTable({ selection, onChange }: PeriodicTableProps) {
  const toggle = (symbol: string) => {
    const current = selection[symbol] ?? 'neutral'
    const next = nextState[current]
    const updated = { ...selection }
    if (next === 'neutral') delete updated[symbol]
    else updated[symbol] = next
    onChange(updated)
  }

  return (
    <div className="periodic-table" aria-label="Element filter">
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
              aria-pressed={state === 'include'}
              title={`${element.number} · ${element.name} · click to cycle include / exclude`}
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
