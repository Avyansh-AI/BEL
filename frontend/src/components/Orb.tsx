import { useEffect, useRef } from 'react'

export type OrbState = 'offline' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'happy' | 'error'

export interface OrbProps {
  state: OrbState
  audioLevel: number
  reducedMotion: boolean
  label?: string
}

// Generate n points distributed over a sphere using a Fibonacci / golden spiral (Roamies formula)
function generateSphere(n: number): [number, number, number][] {
  const points: [number, number, number][] = []
  for (let i = 0; i < n; i++) {
    const y = 1 - (2 * (i + 0.5)) / n
    const r = Math.sqrt(Math.max(0, 1 - y * y))
    const a = i * 2.399963229728653 // Golden angle in radians
    points.push([Math.cos(a) * r, y, Math.sin(a) * r])
  }
  return points
}

const DOTS_520 = generateSphere(520)
const DOTS_260 = generateSphere(260)

export function Orb({ state, audioLevel, reducedMotion, label }: OrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const animFrameRef = useRef<number | null>(null)

  // Mutable animation state across renders
  const stateRef = useRef({
    spin: 0,
    time: 0,
    lastStamp: 0,
    state,
    audioLevel,
    reducedMotion,
  })

  // Synchronize incoming props
  useEffect(() => {
    stateRef.current.state = state
    stateRef.current.audioLevel = audioLevel
    stateRef.current.reducedMotion = reducedMotion
  }, [state, audioLevel, reducedMotion])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let active = true

    const render = (nowMs: number) => {
      if (!active) return

      const s = stateRef.current
      if (s.lastStamp === 0) s.lastStamp = nowMs
      const dt = Math.min((nowMs - s.lastStamp) / 1000, 0.1)
      s.lastStamp = nowMs

      if (!s.reducedMotion) {
        s.time += dt
        const spinRate =
          s.state === 'thinking'
            ? 1.45
            : s.state === 'speaking'
              ? 0.75
              : s.state === 'listening'
                ? 0.52
                : s.state === 'happy'
                  ? 1.1
                  : s.state === 'offline'
                    ? 0.1
                    : 0.32
        s.spin += spinRate * dt
      }

      // Handle device pixel ratio for crisp rendering
      const dpr = window.devicePixelRatio || 1
      const displayWidth = canvas.clientWidth || 320
      const displayHeight = canvas.clientHeight || 320
      const width = Math.floor(displayWidth * dpr)
      const height = Math.floor(displayHeight * dpr)

      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width
        canvas.height = height
      }

      ctx.save()
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, displayWidth, displayHeight)

      const cx = displayWidth / 2
      const cy = displayHeight / 2
      const baseRadius = Math.min(displayWidth, displayHeight) * 0.38

      const t = s.time
      const curState = s.state
      const level = Math.max(0, Math.min(1, s.audioLevel))

      // Breathing scale
      const breath = s.reducedMotion ? 1.0 : 1.0 + (curState === 'offline' ? 0.01 : 0.025) * Math.sin(t * 1.6)

      // Rotation angles
      const yaw = s.spin
      const pitch = -0.38 + (s.reducedMotion ? 0 : Math.sin(t * 0.8) * 0.08)
      const cyw = Math.cos(yaw)
      const syw = Math.sin(yaw)
      const cp = Math.cos(pitch)
      const sp = Math.sin(pitch)

      // Wave ripple amplitude driven by speech/listen
      const isVoiceActive = curState === 'speaking' || curState === 'listening'
      const waveAmp = isVoiceActive ? 0.15 + level * 0.32 : curState === 'happy' ? 0.22 : 0.07

      // Select point density based on display size
      const dots = displayWidth < 200 ? DOTS_260 : DOTS_520

      // Color paletting
      const isError = curState === 'error'
      const isOffline = curState === 'offline'

      // Core heart glow
      const heartRadius = baseRadius * (isOffline ? 0.18 : 0.28 + (isVoiceActive ? level * 0.15 : 0.05 * Math.sin(t * 2)))
      const heartGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, heartRadius * 1.8)
      if (isError) {
        heartGrad.addColorStop(0, 'rgba(255, 180, 110, 0.45)')
        heartGrad.addColorStop(0.5, 'rgba(210, 100, 40, 0.18)')
        heartGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')
      } else if (isOffline) {
        heartGrad.addColorStop(0, 'rgba(120, 150, 180, 0.25)')
        heartGrad.addColorStop(0.5, 'rgba(60, 80, 110, 0.08)')
        heartGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')
      } else {
        heartGrad.addColorStop(0, 'rgba(215, 245, 255, 0.65)')
        heartGrad.addColorStop(0.35, 'rgba(80, 175, 255, 0.32)')
        heartGrad.addColorStop(0.7, 'rgba(30, 100, 240, 0.12)')
        heartGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')
      }
      ctx.fillStyle = heartGrad
      ctx.beginPath()
      ctx.arc(cx, cy, heartRadius * 1.8, 0, Math.PI * 2)
      ctx.fill()

      // Radar sweep angle when thinking
      const radarSweep = (t * 2.8) % (Math.PI * 2)

      // Render 3D particle cloud
      for (let i = 0; i < dots.length; i++) {
        const p = dots[i]

        // Roamies wave calculation: surface harmonic ripple
        const band =
          Math.sin(p[1] * 7 - t * (curState === 'speaking' ? 8.5 : 3.5)) * 0.5 +
          Math.sin(Math.atan2(p[2], p[0]) * 5 + t * 4) * 0.5
        const r = baseRadius * breath * (1 + waveAmp * band)

        // 3D rotation
        let x = p[0] * cyw + p[2] * syw
        let z = -p[0] * syw + p[2] * cyw
        const y = p[1] * cp - z * sp
        z = p[1] * sp + z * cp

        // Screen projection
        const px = cx + x * r
        const py = cy + y * r

        // Shading: Lambertian lighting from top-left with viewer boost
        const lam = Math.max(0, -x * 0.42 - y * 0.52 + z * 0.68)
        let alpha = 0.18 + lam * 0.62 + (z > 0 ? z * 0.2 : 0)

        // Additional wave crest highlight
        if (band > 0) alpha += band * waveAmp * 0.7

        // Radar sweep boost during thinking
        if (curState === 'thinking') {
          const pointAngle = (Math.atan2(y, x) + Math.PI * 2) % (Math.PI * 2)
          const angleDiff = Math.abs(pointAngle - radarSweep)
          if (angleDiff < 0.35 || angleDiff > Math.PI * 2 - 0.35) {
            alpha = Math.min(1.0, alpha + 0.45)
          }
        }

        alpha = Math.max(0.08, Math.min(1.0, alpha))

        // Particle size depends on z (depth)
        const dotSize = Math.max(0.8, (z + 1.2) * 1.25)

        // Draw particle
        ctx.beginPath()
        ctx.arc(px, py, dotSize, 0, Math.PI * 2)

        if (isError) {
          ctx.fillStyle = `rgba(255, 190, 120, ${alpha * 0.9})`
        } else if (isOffline) {
          ctx.fillStyle = `rgba(135, 165, 195, ${alpha * 0.65})`
        } else {
          // Subtle color variation: brighter white/ice-blue at crests, cyan/cobalt on sides
          if (lam > 0.6 || (z > 0.4 && isVoiceActive)) {
            ctx.fillStyle = `rgba(235, 250, 255, ${alpha})`
          } else {
            ctx.fillStyle = `rgba(75, 170, 255, ${alpha * 0.88})`
          }
        }
        ctx.fill()
      }

      ctx.restore()
      animFrameRef.current = requestAnimationFrame(render)
    }

    animFrameRef.current = requestAnimationFrame(render)

    return () => {
      active = false
      if (animFrameRef.current != null) {
        cancelAnimationFrame(animFrameRef.current)
      }
    }
  }, [])

  return (
    <div
      className={`orb-stage orb-stage--${state}`}
      role="img"
      aria-label={label || `BEL is ${state}`}
    >
      <div className="orb-aura" aria-hidden="true" />
      <div className="orb-orbit orb-orbit--back" aria-hidden="true" />
      <canvas
        ref={canvasRef}
        className="orb-canvas"
        style={{
          width: '100%',
          height: '100%',
          display: 'block',
          zIndex: 2,
          pointerEvents: 'none',
        }}
      />
      <div className="orb-orbit orb-orbit--front" aria-hidden="true" />
      <div className="orb-ground-light" aria-hidden="true" />
    </div>
  )
}
