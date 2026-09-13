import { Line, OrbitControls } from '@react-three/drei'
import { Canvas, useThree } from '@react-three/fiber'
import { Suspense, useEffect, useMemo } from 'react'
import { Quaternion, Vector3 } from 'three'

import type { CrystalStructure } from '../api/client'
import { useI18n } from '../i18n'
import { cameraPosition, expandStructure, framingRadius, mutedElementColor, parseRepeats, type View } from '../lib/crystal'

interface InteractiveCrystalProps {
  structure: CrystalStructure
  showCell: boolean
  representation: 'ball_stick' | 'spacefill'
  view: View
  supercell: string
}

export function InteractiveCrystal({ structure, showCell, representation, view, supercell }: InteractiveCrystalProps) {
  const { t } = useI18n()
  const hasWebGL = typeof window !== 'undefined' && (
    typeof window.WebGLRenderingContext !== 'undefined' ||
    typeof window.WebGL2RenderingContext !== 'undefined'
  )

  if (!hasWebGL) {
    return (
      <div className="viewer-unavailable" role="status">
        <span>{t('viewer.webglOffline')}</span>
        <strong>{t('viewer.webglFailed')}</strong>
        <p>{t('viewer.webglFailedBody')}</p>
      </div>
    )
  }

  const expanded = useMemo(() => expandStructure(structure, parseRepeats(supercell)), [structure, supercell])
  const atomScale = representation === 'spacefill' ? 0.74 : 0.34
  const radius = useMemo(() => framingRadius(expanded.sites, atomScale), [atomScale, expanded.sites])

  return (
    <Canvas
      camera={{ position: cameraPosition(view, radius), fov: 38, near: 0.1, far: 1000 }}
      dpr={[1, 1.5]}
      frameloop="demand"
      gl={{ antialias: true, alpha: false }}
      shadows
    >
      <color attach="background" args={['#fbfaf7']} />
      <hemisphereLight args={['#fffafa', '#65555b', 0.8]} />
      <ambientLight intensity={0.32} />
      <directionalLight castShadow position={[-8, 12, 10]} intensity={1.9} color="#fff4f2" />
      <directionalLight position={[8, 3, -6]} intensity={0.4} color="#e5dbe0" />
      <Suspense fallback={null}>
        <CrystalScene sites={expanded.sites} bonds={expanded.bonds} origins={expanded.origins}
                      showCell={showCell} representation={representation}
                      cell={structure.lattice.matrix} />
      </Suspense>
      <CameraRig position={cameraPosition(view, radius)} />
      <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
    </Canvas>
  )
}

/** The camera preset, applied after mount so switching view actually moves it. */
function CameraRig({ position }: { position: [number, number, number] }) {
  const camera = useThree((state) => state.camera)
  const invalidate = useThree((state) => state.invalidate)
  const [x, y, z] = position

  useEffect(() => {
    camera.position.set(x, y, z)
    camera.lookAt(0, 0, 0)
    camera.updateProjectionMatrix()
    invalidate() // frameloop is "demand": without this the new camera is never drawn
  }, [camera, invalidate, x, y, z])

  return null
}

interface SceneProps {
  sites: CrystalStructure['sites']
  bonds: CrystalStructure['bonds']
  origins: number[][]
  cell: number[][]
  showCell: boolean
  representation: 'ball_stick' | 'spacefill'
}

function CrystalScene({ sites, bonds, origins, cell, showCell, representation }: SceneProps) {
  const center = useMemo(() => {
    if (!sites.length) return new Vector3()
    const sum = sites.reduce((value, site) => value.add(new Vector3(...toVector(site.cartesian))), new Vector3())
    return sum.multiplyScalar(1 / sites.length)
  }, [sites])

  return (
    <group position={center.clone().multiplyScalar(-1)}>
      {sites.map((site) => (
        <mesh castShadow receiveShadow key={site.index} position={toVector(site.cartesian)}>
          <sphereGeometry args={[Math.max(0.18, site.radius * (representation === 'spacefill' ? 0.74 : 0.34)), 36, 28]} />
          {representation === 'spacefill'
            ? <meshStandardMaterial color={mutedElementColor(site.color)} metalness={0} roughness={0.58} />
            : <meshLambertMaterial color={mutedElementColor(site.color)} />}
        </mesh>
      ))}
      {representation === 'ball_stick' && bonds.map((bond, index) => {
        const first = sites[bond.from]
        const second = sites[bond.to]
        return first && second ? <Bond key={`${index}-${bond.from}-${bond.to}`} from={first.cartesian} to={second.cartesian} /> : null
      })}
      {showCell && origins.map((origin, index) => (
        <UnitCell key={index} matrix={cell} origin={origin} />
      ))}
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
      <meshLambertMaterial color="#c9c8c3" />
    </mesh>
  )
}

function UnitCell({ matrix, origin }: { matrix: number[][]; origin: number[] }) {
  const corners = useMemo(() => {
    const at = new Vector3(...toVector(origin))
    const a = new Vector3(...toVector(matrix[0] ?? [0, 0, 0]))
    const b = new Vector3(...toVector(matrix[1] ?? [0, 0, 0]))
    const c = new Vector3(...toVector(matrix[2] ?? [0, 0, 0]))
    return [
      at.clone(), at.clone().add(a), at.clone().add(b), at.clone().add(c),
      at.clone().add(a).add(b), at.clone().add(a).add(c),
      at.clone().add(b).add(c), at.clone().add(a).add(b).add(c),
    ]
  }, [matrix, origin])
  const edges = [[0, 1], [0, 2], [0, 3], [1, 4], [1, 5], [2, 4], [2, 6], [3, 5], [3, 6], [4, 7], [5, 7], [6, 7]]

  return <>{edges.map(([from, to]) => <Line key={`${from}-${to}`} points={[corners[from], corners[to]]} color="#728f8d" lineWidth={1.35} transparent opacity={0.72} />)}</>
}

function toVector(values: number[]): [number, number, number] {
  return [values[0] ?? 0, values[1] ?? 0, values[2] ?? 0]
}
