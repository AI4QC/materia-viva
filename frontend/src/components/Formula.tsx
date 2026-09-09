import { formulaParts } from '../lib/crystal'

/**
 * A chemical formula, written the way chemists write it.
 *
 * There used to be two copies of this — one in MaterialResults and one in
 * MaterialDetail — which both subscripted every digit, so `Cd1S1` came out as
 * Cd₁S₁. The parsing lives in `lib/crystal` where it is tested; this is only
 * the markup.
 */
export function Formula({ value }: { value: string }) {
  const parts = formulaParts(value)
  return (
    <>
      {parts.map((part, index) =>
        part.sub ? <sub key={index}>{part.text}</sub> : part.text,
      )}
    </>
  )
}

/** The same formula as plain text, for `aria-label`, `alt` and `title`. */
export function formulaText(value: string): string {
  return formulaParts(value).map((part) => part.text).join('')
}
