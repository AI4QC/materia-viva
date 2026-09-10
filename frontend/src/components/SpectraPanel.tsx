import { useEffect, useMemo, useRef, useState } from 'react'

import {
  curveUrl,
  getCurve,
  getXrd,
  type CurvePayload,
  type MaterialCurve,
  type XrdPattern,
} from '../api/client'
import { useI18n, type TranslationKey } from '../i18n'

interface SpectraPanelProps {
  materialId: string
  curves: MaterialCurve[]
}

/** Full-width spectra area: simulated + measured XRD, stored curves, band plots. */
export function SpectraPanel({ materialId, curves }: SpectraPanelProps) {
  const { t } = useI18n()
  const xrdCurves = curves.filter((curve) => curve.curve_type === 'xrd')
  const bandCount = curves.filter((curve) => curve.curve_type === 'band_structure').length
  const dosCount = curves.filter((curve) => curve.curve_type === 'dos').length
  const phononCount = curves.filter((curve) => curve.curve_type.startsWith('phonon')).length
  const xyCurves = curves.filter(
    (curve) => curve.fmt !== 'svg' && curve.curve_type !== 'xrd',
  )
  const svgCurves = curves.filter((curve) => curve.fmt === 'svg')
  return (
    <section className="property-section detail-spectra" aria-label={t('spectra.label')}>
      <p className="spectra-intro">{t('spectra.intro')}</p>
      <div className="spectra-availability" aria-label={t('spectra.availability')}>
        <SpectrumStatus count={bandCount} label={t('spectra.bandStructure')} />
        <SpectrumStatus count={dosCount} label={t('spectra.electronicDos')} />
        <SpectrumStatus count={phononCount} label={t('spectra.phonons')} />
        <SpectrumStatus count={xrdCurves.length} label={t('spectra.xrd')} simulated />
      </div>
      <div className="spectra-grid">
        <XrdPanel materialId={materialId} stored={xrdCurves} />
        {xyCurves.map((curve) => (
          <StoredCurvePanel key={curve.id} materialId={materialId} curve={curve} />
        ))}
      </div>
      {svgCurves.length > 0 && (
        <div className="bandplot-grid">
          {svgCurves.map((curve) => (
            <figure className="bandplot" key={curve.id}>
              <img
                alt={`${curve.label ?? curveTypeLabel(curve.curve_type, t)} — ${curve.source_name}`}
                loading="lazy"
                src={curveUrl(materialId, curve.id)}
              />
              <figcaption>
                <span>{curve.label ?? curveTypeLabel(curve.curve_type, t)}</span>
                <span className="chart-source">{curve.source_name}</span>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </section>
  )
}

function SpectrumStatus({ count, label, simulated = false }: { count: number; label: string; simulated?: boolean }) {
  const { t } = useI18n()
  return (
    <div data-available={count > 0 || simulated}>
      <span>{label}</span>
      <strong>{count > 0 ? t('spectra.records', { count: String(count) }) : simulated ? t('spectra.simulationReady') : t('spectra.notRecorded')}</strong>
    </div>
  )
}

function curveTypeLabel(type: string, t: (key: TranslationKey) => string) {
  if (type === 'band_structure') return t('spectra.bandStructure')
  if (type === 'dos') return t('spectra.electronicDos')
  if (type === 'phonon_dos') return t('spectra.phononDos')
  if (type === 'raman') return t('spectra.raman')
  if (type === 'ir') return t('spectra.ir')
  if (type === 'xas') return t('spectra.xas')
  if (type === 'absorption') return t('spectra.absorption')
  if (type === 'kappa_spectral') return t('spectra.kappaSpectral')
  if (type === 'kappa_cumulative') return t('spectra.kappaCumulative')
  return type.replace(/_/g, ' ')
}

function XrdPanel({ materialId, stored }: { materialId: string; stored: MaterialCurve[] }) {
  const { t } = useI18n()
  const [computed, setComputed] = useState<XrdPattern | null>(null)
  const [measured, setMeasured] = useState<{ curve: MaterialCurve; data: CurvePayload } | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading')

  useEffect(() => {
    const controller = new AbortController()
    setComputed(null)
    setMeasured(null)
    setState('loading')
    getXrd(materialId, controller.signal)
      .then((pattern) => { setComputed(pattern); setState('ready') })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setState('failed')
      })
    const first = stored[0]
    if (first) {
      getCurve(materialId, first.id, controller.signal)
        .then((data) => setMeasured({ curve: first, data }))
        .catch(() => undefined)
    }
    return () => controller.abort()
  }, [materialId, stored])

  if (state === 'failed' && !measured) {
    return (
      <figure className="chart-card">
        <figcaption><span>{t('spectra.xrd')}</span></figcaption>
        <p className="provenance-note">{t('spectra.xrdFailed')}</p>
      </figure>
    )
  }
  return (
    <figure className="chart-card">
      <figcaption>
        <span>{t('spectra.xrd')}</span>
        {computed && <span className="chart-source">{computed.wavelength}</span>}
      </figcaption>
      {state === 'loading' && !computed ? (
        <p className="provenance-note">{t('spectra.loading')}</p>
      ) : (
        <XrdChart computed={computed} measured={measured} />
      )}
      <div className="chart-legend">
        {computed && (
          <span><i className="legend-swatch legend-swatch--sticks" /> {t('spectra.simulated')}</span>
        )}
        {measured && (
          <span>
            <i className="legend-swatch legend-swatch--line" /> {t('spectra.measured')} · {measured.curve.source_name}
          </span>
        )}
      </div>
    </figure>
  )
}

const WIDTH = 640
const HEIGHT = 240
const PAD = { left: 42, right: 12, top: 10, bottom: 30 }

function XrdChart({ computed, measured }: {
  computed: XrdPattern | null
  measured: { curve: MaterialCurve; data: CurvePayload } | null
}) {
  const { t } = useI18n()
  const [hover, setHover] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)

  const xs = [
    ...(computed?.x ?? []),
    ...(measured?.data.x ?? []),
  ]
  const xMin = Math.min(...xs, 5)
  const xMax = Math.max(...xs, 90)
  const plotW = WIDTH - PAD.left - PAD.right
  const plotH = HEIGHT - PAD.top - PAD.bottom
  const toX = (value: number) => PAD.left + ((value - xMin) / (xMax - xMin)) * plotW
  const toY = (value: number) => PAD.top + (1 - value / 100) * plotH

  const measuredPath = useMemo(() => {
    if (!measured) return null
    const { x, y } = measured.data
    if (!x.length) return null
    const yMax = Math.max(...y, 1e-9)
    return x.map((value, index) =>
      `${index === 0 ? 'M' : 'L'}${toX(value).toFixed(1)},${toY((y[index] / yMax) * 100).toFixed(1)}`,
    ).join('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measured, xMin, xMax])

  const nearestPeak = (eventX: number): number | null => {
    if (!computed?.x?.length) return null
    let best = 0
    let bestDist = Infinity
    computed.x.forEach((value, index) => {
      const dist = Math.abs(toX(value) - eventX)
      if (dist < bestDist) { bestDist = dist; best = index }
    })
    return bestDist < 18 ? best : null
  }

  const ticks = []
  for (let tick = Math.ceil(xMin / 10) * 10; tick <= xMax; tick += 10) ticks.push(tick)

  return (
    <svg
      className="chart"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(event) => {
        const rect = svgRef.current?.getBoundingClientRect()
        if (!rect) return
        setHover(nearestPeak(((event.clientX - rect.left) / rect.width) * WIDTH))
      }}
      ref={svgRef}
      role="img"
      aria-label={t('spectra.xrd')}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
    >
      <line className="chart-axis" x1={PAD.left} x2={WIDTH - PAD.right} y1={HEIGHT - PAD.bottom} y2={HEIGHT - PAD.bottom} />
      {ticks.map((tick) => (
        <g key={tick}>
          <line className="chart-grid" x1={toX(tick)} x2={toX(tick)} y1={PAD.top} y2={HEIGHT - PAD.bottom} />
          <text className="chart-tick" textAnchor="middle" x={toX(tick)} y={HEIGHT - PAD.bottom + 14}>{tick}°</text>
        </g>
      ))}
      <text className="chart-tick" textAnchor="middle" transform={`rotate(-90 12 ${HEIGHT / 2})`} x={12} y={HEIGHT / 2}>
        {t('spectra.intensity')}
      </text>
      <text className="chart-tick" textAnchor="middle" x={PAD.left + plotW / 2} y={HEIGHT - 4}>2θ (deg)</text>
      {measuredPath && <path className="chart-line chart-line--measured" d={measuredPath} />}
      {(computed?.x ?? []).map((value, index) => (
        <line
          className={`chart-stick${hover === index ? ' chart-stick--hover' : ''}`}
          key={index}
          x1={toX(value)}
          x2={toX(value)}
          y1={HEIGHT - PAD.bottom}
          y2={toY(computed?.y[index] ?? 0)}
        />
      ))}
      {hover !== null && computed?.x && (
        <g className="chart-tooltip" transform={`translate(${Math.min(toX(computed.x[hover]) + 8, WIDTH - 150)}, ${PAD.top + 6})`}>
          <rect height={46} rx={2} width={142} />
          <text x={8} y={16}>2θ = {computed.x[hover].toFixed(2)}°</text>
          <text x={8} y={29}>I = {computed.y[hover].toFixed(1)}</text>
          <text x={8} y={42}>{computed.hkl?.[hover] ?? ''}</text>
        </g>
      )}
    </svg>
  )
}

function StoredCurvePanel({ materialId, curve }: { materialId: string; curve: MaterialCurve }) {
  const { t } = useI18n()
  const [data, setData] = useState<CurvePayload | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setFailed(false)
    getCurve(materialId, curve.id, controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setFailed(true)
      })
    return () => controller.abort()
  }, [materialId, curve.id])

  return (
    <figure className="chart-card">
      <figcaption>
        <span>{curve.label ?? curveTypeLabel(curve.curve_type, t)}{curve.method ? ` · ${curve.method}` : ''}</span>
        <span className="chart-source">{curve.source_name}</span>
      </figcaption>
      {failed ? (
        <p className="provenance-note">{t('spectra.curveFailed')}</p>
      ) : !data ? (
        <p className="provenance-note">{t('spectra.curveLoading')}</p>
      ) : (
        <LineChart data={data} />
      )}
    </figure>
  )
}

const SERIES_COLORS = ['#8f2f48', '#4f7088', '#69805e', '#9a6f55', '#71657e', '#a45f68', '#4f7f7a', '#947f47']

export function curveTraces(data: CurvePayload) {
  return [
    { name: data.y_label ?? 'Total', y: data.y, color: 'var(--brand-accent)' },
    ...(data.series ?? []).map((series, index) => ({
      name: series.name,
      y: series.y,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
    })),
  ].filter((trace) => trace.y.length === data.x.length)
}

function LineChart({ data }: { data: CurvePayload }) {
  const [hover, setHover] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const { x } = data
  if (!x.length) return null
  const traces = curveTraces(data)
  const values = traces.flatMap((trace) => trace.y)
  const xMin = x[0]
  const xMax = x[x.length - 1] || 1
  const yMax = Math.max(...values, 1e-9)
  const yMin = Math.min(...values, 0)
  const plotW = WIDTH - PAD.left - PAD.right
  const plotH = HEIGHT - PAD.top - PAD.bottom
  const toX = (value: number) => PAD.left + ((value - xMin) / (xMax - xMin || 1)) * plotW
  const toY = (value: number) => PAD.top + (1 - (value - yMin) / (yMax - yMin || 1)) * plotH
  const path = (y: number[]) => x.map((value, index) =>
    `${index === 0 ? 'M' : 'L'}${toX(value).toFixed(1)},${toY(y[index]).toFixed(1)}`,
  ).join('')
  const tickCount = 6
  const ticks = Array.from({ length: tickCount + 1 }, (_, index) => xMin + ((xMax - xMin) / tickCount) * index)

  return (<>
    <svg
      className="chart"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(event) => {
        const rect = svgRef.current?.getBoundingClientRect()
        if (!rect) return
        const px = ((event.clientX - rect.left) / rect.width) * WIDTH
        const fraction = (px - PAD.left) / plotW
        const index = Math.round(fraction * (x.length - 1))
        setHover(index >= 0 && index < x.length ? index : null)
      }}
      ref={svgRef}
      role="img"
      aria-label={data.y_label ?? 'curve'}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
    >
      <line className="chart-axis" x1={PAD.left} x2={WIDTH - PAD.right} y1={HEIGHT - PAD.bottom} y2={HEIGHT - PAD.bottom} />
      {ticks.map((tick, index) => (
        <text className="chart-tick" key={index} textAnchor="middle" x={toX(tick)} y={HEIGHT - PAD.bottom + 14}>
          {Math.abs(tick) >= 100 ? tick.toFixed(0) : tick.toFixed(1)}
        </text>
      ))}
      <text className="chart-tick" textAnchor="middle" x={PAD.left + plotW / 2} y={HEIGHT - 4}>
        {data.x_label ?? 'x'}{data.x_unit ? ` (${data.x_unit})` : ''}
      </text>
      <text className="chart-tick" textAnchor="middle" transform={`rotate(-90 12 ${HEIGHT / 2})`} x={12} y={HEIGHT / 2}>
        {data.y_label ?? 'y'}{data.y_unit ? ` (${data.y_unit})` : ''}
      </text>
      {traces.map((trace, index) => (
        <path className="chart-line" d={path(trace.y)} key={`${trace.name}-${index}`} style={{ stroke: trace.color }}>
          <title>{trace.name}</title>
        </path>
      ))}
      {hover !== null && (
        <g>
          <line className="chart-crosshair" x1={toX(x[hover])} x2={toX(x[hover])} y1={PAD.top} y2={HEIGHT - PAD.bottom} />
          <g className="chart-tooltip" transform={`translate(${Math.min(toX(x[hover]) + 8, WIDTH - 150)}, ${PAD.top + 6})`}>
            <rect height={33} rx={2} width={142} />
            <text x={8} y={16}>{data.x_label ?? 'x'} = {x[hover].toFixed(2)}</text>
            <text x={8} y={29}>{data.y_label ?? 'y'} = {data.y[hover].toPrecision(4)}</text>
          </g>
        </g>
      )}
    </svg>
    {traces.length > 1 && (
      <div className="chart-series-legend" aria-label={`${traces.length} series`}>
        {traces.map((trace, index) => <span key={`${trace.name}-${index}`}><i style={{ background: trace.color }} />{trace.name}</span>)}
      </div>
    )}
  </>)
}
