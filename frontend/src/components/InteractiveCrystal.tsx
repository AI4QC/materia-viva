import { Line, OrbitControls } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { Suspense, useMemo } from 'react'
import { Quaternion, Vector3 } from 'three'

import type { CrystalStructure } from '../api/client'
import { useI18n } from '../i18n'

interface InteractiveCrystalProps {
  structure: CrystalStructure
  showCell: boolean
  representation: 'ball_stick' | 'spacefill'
}

export function InteractiveCrystal({ structure, showCell, representation }: InteractiveCrystalProps) {
  const { t } = useI18n()
  const hasWebGL = typeof window !== 'undefined' && (
    typeof window.WebGLRenderingContext !== 'undefined' ||
    typeof window.WebGL2RenderingContext !== 'undefined'
  )

  if (!hasWebGL) {
    return (
      <div className="viewer-unavailable" role="status">
        <span>WEBGL OFFLINE</span>
        <strong>{t('viewer.webglFailed')}</strong>
        <p>{t('viewer.webglFailedBody')}</p>
      </div>
    )
  }

  return (
    <Canvas
      camera={{ position: [9, 8, 10], fov: 38, near: 0.1, far: 1000 }}
      dpr={[1, 1.5]}
      frameloop="demand"
      gl={{ antialias: true, alpha: false }}
    >
      <color attach="background" args={['#071110']} />
      <ambientLight intensity={1.5} />
      <directionalLight position={[8, 12, 10]} intensity={2.6} color="#fff4dd" />
      <directionalLight position={[-8, -4, -6]} intensity={1.1} color="#62e6b1" />
      <Suspense fallback={null}>
        <CrystalScene structure={structure} showCell={showCell} representation={representation} />
      </Suspense>
      <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
    </Canvas>
  )
}

function CrystalScene({ structure, showCell, representation }: InteractiveCrystalProps) {
  const center = useMemo(() => {
    if (!structure.sites.length) return new Vector3()
    const sum = structure.sites.reduce((value, site) => value.add(new Vector3(...toVector(site.cartesian))), new Vector3())
    return sum.multiplyScalar(1 / structure.sites.length)
  }, [structure.sites])

  return (
    <group position={center.clone().multiplyScalar(-1)}>
      {structure.sites.map((site) => (
        <mesh key={site.index} position={toVector(site.cartesian)}>
          <sphereGeometry args={[Math.max(0.18, site.radius * (representation === 'spacefill' ? 0.74 : 0.34)), 28, 20]} />
          <meshStandardMaterial color={rgb(site.color)} roughness={0.27} metalness={0.06} />
        </mesh>
      ))}
      {representation === 'ball_stick' && structure.bonds.map((bond) => {
        const first = structure.sites[bond.from]
        const second = structure.sites[bond.to]
        return first && second ? <Bond key={`${bond.from}-${bond.to}`} from={first.cartesian} to={second.cartesian} /> : null
      })}
      {showCell && <UnitCell matrix={structure.lattice.matrix} />}
    </group>
  )
}

function Bond({ from, to }: { from: number[]; to: number[] }) {
  const transform = useMemo(() => {
    const start = new Vector3(...toVector(from))
    const end = new Vector3(...toVector(to))
    const direction = end.clone().sub(start)
    return {
      length: direction.length(),
      midpoint: start.add(end).multiplyScalar(0.5),
      quaternion: new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), direction.normalize()),
    }
  }, [from, to])

  return (
    <mesh position={transform.midpoint} quaternion={transform.quaternion}>
      <cylinderGeometry args={[0.065, 0.065, transform.length, 12]} />
      <meshStandardMaterial color="#cbd5d0" roughness={0.55} />
    </mesh>
  )
}

function UnitCell({ matrix }: { matrix: number[][] }) {
  const corners = useMemo(() => {
    const a = new Vector3(...toVector(matrix[0] ?? [0, 0, 0]))
    const b = new Vector3(...toVector(matrix[1] ?? [0, 0, 0]))
    const c = new Vector3(...toVector(matrix[2] ?? [0, 0, 0]))
    return [
      new Vector3(), a, b, c,
      a.clone().add(b), a.clone().add(c), b.clone().add(c), a.clone().add(b).add(c),
    ]
  }, [matrix])
  const edges = [[0, 1], [0, 2], [0, 3], [1, 4], [1, 5], [2, 4], [2, 6], [3, 5], [3, 6], [4, 7], [5, 7], [6, 7]]

  return <>{edges.map(([from, to]) => <Line key={`${from}-${to}`} points={[corners[from], corners[to]]} color="#62e6b1" lineWidth={1} transparent opacity={0.7} />)}</>
}

function toVector(values: number[]): [number, number, number] {
  return [values[0] ?? 0, values[1] ?? 0, values[2] ?? 0]
}

function rgb(color: number[]) {
  return `rgb(${color.slice(0, 3).map((value) => Math.round(value * 255)).join(',')})`
}
