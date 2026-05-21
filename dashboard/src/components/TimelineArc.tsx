import { motion } from 'framer-motion';
import type { TimelineBlock } from '../lib/api';
import { formatDate, EASE_OUT_EXPO } from '../lib/constants';

interface Props {
  timeline: TimelineBlock;
}

/**
 * Insolvency-arc visualization. Half-circle from 180° (signal onset, left)
 * to 0° (estimated konkurs, right). Current position marked along the arc.
 *
 * Geometry:
 *   - viewBox 0 0 360 200, half circle of radius 150 centered at (180, 180)
 *   - angle θ = π - (elapsed / median) * π
 *   - position = (180 + 150·cos(θ), 180 - 150·sin(θ))
 *
 * When no onset → render the empty arc with both endpoints labeled but no
 * current-position marker.
 */
export function TimelineArc({ timeline }: Props) {
  const elapsed = timeline.days_elapsed;
  const median = timeline.median_days_to_konkurs;
  const remaining = timeline.days_remaining;
  const hasOnset = elapsed != null && median > 0;

  // Clamp elapsed/median to [0, 1] for the marker.
  const fraction = hasOnset ? Math.min(1, Math.max(0, elapsed! / median)) : null;

  const W = 360;
  const H = 200;
  const CX = 180;
  const CY = 180;
  const R = 150;

  // Arc endpoints (180° start at left, 0° end at right).
  const start = { x: CX - R, y: CY };
  const end = { x: CX + R, y: CY };

  // Marker position along the arc.
  const theta = fraction != null ? Math.PI - fraction * Math.PI : null;
  const marker = theta != null
    ? { x: CX + R * Math.cos(theta), y: CY - R * Math.sin(theta) }
    : null;

  return (
    <div className="timeline">
      <div className="uppercase-label">Insolvensbåge</div>

      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Insolvensbåge">
        <defs>
          <linearGradient id="arcGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"  stopColor="var(--teal)" stopOpacity="0.8" />
            <stop offset="50%" stopColor="var(--amber)" stopOpacity="0.6" />
            <stop offset="100%" stopColor="var(--red)" stopOpacity="0.9" />
          </linearGradient>
          <filter id="markerGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Background arc (faint) */}
        <path
          d={`M ${start.x} ${start.y} A ${R} ${R} 0 0 1 ${end.x} ${end.y}`}
          fill="none"
          stroke="var(--border-2)"
          strokeWidth={1}
        />

        {/* Filled arc — animates draw-on if onset exists */}
        {fraction != null && (
          <motion.path
            d={`M ${start.x} ${start.y} A ${R} ${R} 0 0 1 ${end.x} ${end.y}`}
            fill="none"
            stroke="url(#arcGradient)"
            strokeWidth={2}
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: fraction }}
            transition={{ duration: 1.0, ease: EASE_OUT_EXPO, delay: 0.4 }}
          />
        )}

        {/* Start endpoint */}
        <circle cx={start.x} cy={start.y} r={4} fill="var(--teal)" />
        <text
          x={start.x}
          y={start.y - 14}
          textAnchor="middle"
          fontSize={9}
          fontFamily="var(--font-mono)"
          fill="var(--sand-2)"
          letterSpacing="0.05em"
        >
          SIGNALSTART
        </text>
        <text
          x={start.x}
          y={start.y + 18}
          textAnchor="middle"
          fontSize={10}
          fontFamily="var(--font-mono)"
          fill="var(--muted)"
        >
          {timeline.signal_onset_date ? formatDate(timeline.signal_onset_date) : '—'}
        </text>

        {/* End endpoint */}
        <circle cx={end.x} cy={end.y} r={4} fill="var(--red)" />
        <text
          x={end.x}
          y={end.y - 14}
          textAnchor="middle"
          fontSize={9}
          fontFamily="var(--font-mono)"
          fill="var(--sand-2)"
          letterSpacing="0.05em"
        >
          UPPSKATTAD KONKURS
        </text>
        <text
          x={end.x}
          y={end.y + 18}
          textAnchor="middle"
          fontSize={10}
          fontFamily="var(--font-mono)"
          fill="var(--muted)"
        >
          {remaining != null ? `~${remaining} dagar` : '—'}
        </text>

        {/* Current position marker */}
        {marker && (
          <motion.g
            initial={{ opacity: 0, scale: 0 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6, ease: EASE_OUT_EXPO, delay: 1.2 }}
          >
            <circle
              cx={marker.x}
              cy={marker.y}
              r={9}
              fill="var(--red-pulse)"
              filter="url(#markerGlow)"
            />
            <circle
              cx={marker.x}
              cy={marker.y}
              r={6}
              fill="var(--red)"
            />
            <text
              x={marker.x}
              y={marker.y - 18}
              textAnchor="middle"
              fontSize={9}
              fontFamily="var(--font-mono)"
              fill="var(--sand)"
              letterSpacing="0.1em"
            >
              IDAG
            </text>
            <text
              x={marker.x}
              y={marker.y + 22}
              textAnchor="middle"
              fontSize={11}
              fontFamily="var(--font-mono)"
              fill="var(--sand)"
              fontWeight={500}
            >
              {elapsed} / {median} dagar
            </text>
          </motion.g>
        )}
      </svg>

      {!hasOnset && (
        <div className="timeline-empty">
          Inga aktiva signaler — bolaget är inte på insolvensbågen idag.
        </div>
      )}

      <style>{`
        .timeline {
          display: flex;
          flex-direction: column;
          gap: 14px;
          flex: 1;
          min-width: 0;
        }
        .timeline svg { max-height: 240px; }
        .timeline-empty {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--muted);
          padding: 12px;
          border: 1px dashed var(--border);
          border-radius: 2px;
        }
      `}</style>
    </div>
  );
}
