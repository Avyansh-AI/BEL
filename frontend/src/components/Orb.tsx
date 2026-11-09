import { motion } from 'framer-motion'
export type OrbState = 'offline' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'happy' | 'error'

export function Orb({ state, audioLevel, reducedMotion, label }: { state: OrbState; audioLevel: number; reducedMotion: boolean; label?: string }) {
  const activeScale = state === 'listening'
    ? 1 + Math.min(audioLevel, 0.7) * 0.12
    : state === 'speaking'
      ? 1 + Math.min(audioLevel, 0.55) * 0.08
      : undefined
  const animate = reducedMotion
    ? { y: 0, scale: state === 'listening' || state === 'speaking' ? 1.012 : 1 }
    : state === 'happy'
      ? { y: [0, -14, 0], scale: [1, 1.04, 1] }
      : state === 'thinking'
        ? { y: [0, -3, 0], scale: [1, 1.012, 0.995, 1] }
        : state === 'listening'
          ? { y: 0, scale: activeScale ?? 1.025 }
          : state === 'speaking'
            ? { y: 0, scale: activeScale ?? [1, 1.025, 0.99, 1.018, 1] }
            : state === 'error'
              ? { y: 0, scale: [1, 1.025, 1] }
              : { y: [0, -8, 0], scale: [1, 1.018, 1] }
  const transition = reducedMotion
    ? { duration: 0 }
    : state === 'happy'
      ? { duration: 0.85, repeat: 2, ease: 'easeInOut' as const }
      : state === 'thinking'
        ? { duration: 2.4, repeat: Infinity, ease: 'easeInOut' as const }
        : state === 'speaking'
          ? { duration: 0.92, repeat: Infinity, ease: 'easeInOut' as const }
          : state === 'listening'
            ? { type: 'spring' as const, stiffness: 145, damping: 17 }
            : state === 'error'
              ? { duration: 0.24, repeat: 2, ease: 'easeInOut' as const }
              : { duration: 4.5, repeat: Infinity, ease: 'easeInOut' as const }
  const animateAura = !reducedMotion && (state === 'speaking' || state === 'listening')

  return (
    <div className={`orb-stage orb-stage--${state}`} role="img" aria-label={label || `BEL is ${state}`}>
      <motion.div className="orb-aura" animate={animateAura ? { opacity: [0.4, 0.72, 0.4], scale: [0.94, 1.08, 0.94] } : { opacity: state === 'offline' ? 0.42 : 0.58, scale: 1 }} transition={{ duration: reducedMotion ? 0 : 2.1, repeat: animateAura ? Infinity : 0, ease: 'easeInOut' }} />
      <div className="orb-orbit orb-orbit--back" aria-hidden="true" />
      <motion.div className="orb" animate={animate} transition={transition}>
        <div className="orb-sheen" />
        <div className="orb-core-light" />
        <div className="orb-current orb-current--one" />
        <div className="orb-current orb-current--two" />
        <div className="orb-current orb-current--three" />
        <div className="orb-vortex orb-vortex--one" />
        <div className="orb-vortex orb-vortex--two" />
        <div className="orb-nucleus" />
        <div className="orb-glint" />
      </motion.div>
      <div className="orb-orbit orb-orbit--front" aria-hidden="true" />
      <div className="orb-ground-light" />
    </div>
  )
}

