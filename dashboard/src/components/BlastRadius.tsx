import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import { motion } from 'framer-motion';
import L from 'leaflet';

import {
  type ContagionMap,
  type ContagionPeer,
  type NorricEnvelope,
  type RiskTier,
} from '../lib/api';
import {
  TIER_COLOR,
  TIER_LABEL_SV,
  TIMING,
  EASE_OUT_EXPO,
  MATCH_REASON_LABEL_SV,
} from '../lib/constants';

interface Props {
  envelope: NorricEnvelope<ContagionMap>;
}

interface Pt { x: number; y: number; }
interface ProjectedPeer extends Pt {
  peer: ContagionPeer;
  ringIdx: number;
  matchReason: string;
}

const NODE_SIZE_BY_TIER: Record<RiskTier, number> = {
  CRITICAL: 28,
  HIGH:     24,
  ELEVATED: 20,
  WATCH:    18,
  HEALTHY:  16,
};

const NODE_FILL_BY_TIER: Record<RiskTier, string> = {
  CRITICAL: 'var(--red)',
  HIGH:     'var(--amber)',
  ELEVATED: 'rgba(242, 237, 228, 0.40)',
  WATCH:    'rgba(93, 202, 165, 0.50)',
  HEALTHY:  'rgba(29, 158, 117, 0.50)',
};

export function BlastRadius({ envelope }: Props) {
  const data = envelope.data;
  const source = data.source;

  if (!source || source.lat == null || source.lng == null) {
    return (
      <EmptyState
        title="Ingen geografisk förankring"
        detail={
          source
            ? `Källföretaget finns i norric_entities men saknar kommunkod-koordinater.`
            : `Företaget finns inte i norric_entities.`
        }
      />
    );
  }

  const allPts: Array<{ lat: number; lng: number }> = [
    { lat: source.lat, lng: source.lng },
  ];
  const peers: Array<{
    peer: ContagionPeer;
    ringIdx: number;
    matchReason: string;
  }> = [];

  data.rings.forEach((ring, idx) => {
    ring.peers.forEach((p) => {
      if (p.lat != null && p.lng != null) {
        allPts.push({ lat: p.lat, lng: p.lng });
        peers.push({ peer: p, ringIdx: idx + 1, matchReason: ring.match_reason });
      }
    });
  });

  // Pad bounds 20% so nothing hugs the map edges.
  const bounds = computePaddedBounds(allPts, 0.25);

  return (
    <section className="blast">
      <header className="blast-header">
        <span className="uppercase-label">Leveranskedjans blast radius</span>
        <span className="blast-source-name">
          {source.name ?? source.orgnr}
        </span>
        <span className="blast-tier" style={{ color: source.tier ? TIER_COLOR[source.tier] : 'var(--muted)' }}>
          {source.tier ? TIER_LABEL_SV[source.tier] : '—'}
        </span>
      </header>

      <div className="blast-stage">
        <MapContainer
          bounds={bounds}
          zoomControl={false}
          dragging={false}
          touchZoom={false}
          scrollWheelZoom={false}
          doubleClickZoom={false}
          boxZoom={false}
          keyboard={false}
          attributionControl={true}
          style={{ width: '100%', height: '100%' }}
        >
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png"
            attribution='&copy; OpenStreetMap &copy; CARTO'
            subdomains="abcd"
            maxZoom={18}
          />
          <BlastOverlay source={source} peers={peers} />
        </MapContainer>
      </div>

      <BlastSummary data={data} />

      <style>{`
        .blast {
          border: 1px solid var(--border-2);
          background: var(--ink);
          border-radius: 4px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }
        .blast-header {
          padding: 18px 24px;
          display: flex;
          align-items: baseline;
          gap: 16px;
          border-bottom: 1px solid var(--border);
        }
        .blast-source-name {
          font-family: var(--font-display);
          font-style: italic;
          font-weight: 600;
          font-size: 18px;
          color: var(--sand);
        }
        .blast-tier {
          font-family: var(--font-ui);
          font-size: 10px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          font-weight: 600;
          margin-left: auto;
        }
        .blast-stage {
          height: 520px;
          position: relative;
          background: var(--void);
        }
      `}</style>
    </section>
  );
}

/* ── Overlay rendered inside the Leaflet map context ──────────────────────── */

function BlastOverlay({
  source,
  peers,
}: {
  source: NonNullable<ContagionMap['source']>;
  peers: Array<{ peer: ContagionPeer; ringIdx: number; matchReason: string }>;
}) {
  const map = useMap();
  const [, force] = useState(0);

  // Re-project on resize / zoom-snap.
  useEffect(() => {
    const onChange = () => force((n) => n + 1);
    map.on('zoomend moveend resize', onChange);
    // Initial nudge so we render once the map has settled.
    const t = window.setTimeout(onChange, 60);
    return () => {
      map.off('zoomend moveend resize', onChange);
      window.clearTimeout(t);
    };
  }, [map]);

  const size = map.getSize();
  const W = size.x;
  const H = size.y;

  const epicenter: Pt = useMemo(() => {
    const pt = map.latLngToContainerPoint(L.latLng(source.lat!, source.lng!));
    return { x: pt.x, y: pt.y };
  }, [map, source.lat, source.lng, W, H]);

  const projectedPeers: ProjectedPeer[] = useMemo(
    () =>
      peers.map(({ peer, ringIdx, matchReason }) => {
        const pt = map.latLngToContainerPoint(L.latLng(peer.lat!, peer.lng!));
        return { x: pt.x, y: pt.y, peer, ringIdx, matchReason };
      }),
    [map, peers, W, H],
  );

  // Decorative ring radii — chosen relative to map dimensions so they
  // scale with the container without overflowing.
  const minDim = Math.min(W, H);
  const ringRadii = [Math.max(80, minDim * 0.22), Math.max(140, minDim * 0.38)];

  return (
    <svg
      className="blast-overlay"
      width="100%"
      height="100%"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 400,
      }}
    >
      <defs>
        <filter id="epicenterGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {/* Connecting lines — traced from epicenter outward, staggered */}
      {projectedPeers.map((p, i) => (
        <motion.line
          key={`line-${i}`}
          x1={epicenter.x}
          y1={epicenter.y}
          x2={p.x}
          y2={p.y}
          stroke={lineColorForTier(p.peer.tier)}
          strokeWidth={0.5}
          strokeDasharray="4 4"
          initial={{ pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: 1 }}
          transition={{
            duration: 0.3,
            delay: (TIMING.linesStart + i * 60) / 1000,
            ease: 'easeOut',
          }}
        />
      ))}

      {/* Decorative expanding rings — purely visual, centered on epicenter */}
      {ringRadii.map((r, i) => (
        <motion.circle
          key={`ring-${i}`}
          cx={epicenter.x}
          cy={epicenter.y}
          r={r}
          fill="none"
          stroke={ringStrokeForIdx(i)}
          strokeWidth={0.5}
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          style={{ transformOrigin: `${epicenter.x}px ${epicenter.y}px` }}
          transition={{
            duration: i === 0 ? TIMING.ringExpand / 1000 : 0.5,
            delay: (i === 0 ? TIMING.ring1Start : TIMING.ring2Start) / 1000,
            ease: EASE_OUT_EXPO,
          }}
        />
      ))}

      {/* Peer nodes — fade in with stagger per ring */}
      {projectedPeers.map((p, i) => {
        const tier = (p.peer.tier ?? 'ELEVATED') as RiskTier;
        const size = NODE_SIZE_BY_TIER[tier];
        const isCritical = tier === 'CRITICAL';
        const startMs = p.ringIdx === 1 ? 600 : 1100;
        return (
          <motion.g
            key={`peer-${i}`}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{
              duration: 0.4,
              delay: (startMs + i * TIMING.ringStagger) / 1000,
              ease: EASE_OUT_EXPO,
            }}
            style={{ transformOrigin: `${p.x}px ${p.y}px` }}
          >
            <circle
              cx={p.x}
              cy={p.y}
              r={size / 2}
              fill={NODE_FILL_BY_TIER[tier]}
              stroke={isCritical ? 'var(--gold)' : 'rgba(13,13,12,0.8)'}
              strokeWidth={isCritical ? 1.5 : 1}
            />
            <text
              x={p.x}
              y={p.y + size / 2 + 12}
              textAnchor="middle"
              fontSize={10}
              fontFamily="var(--font-mono)"
              fill="var(--sand-2)"
              style={{ paintOrder: 'stroke', stroke: 'var(--void)', strokeWidth: 3 }}
            >
              {truncateName(p.peer.name)}
            </text>
            {p.peer.score != null && (
              <text
                x={p.x}
                y={p.y + 3}
                textAnchor="middle"
                fontSize={9}
                fontFamily="var(--font-mono)"
                fill="var(--void)"
                fontWeight={700}
              >
                {p.peer.score}
              </text>
            )}
          </motion.g>
        );
      })}

      {/* Epicenter — always last so it sits on top */}
      <motion.g
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.4, ease: EASE_OUT_EXPO }}
        style={{ transformOrigin: `${epicenter.x}px ${epicenter.y}px` }}
      >
        {/* Pulse ring */}
        <motion.circle
          cx={epicenter.x}
          cy={epicenter.y}
          r={32}
          fill="var(--red-pulse)"
          animate={{ scale: [1, 1.6, 1], opacity: [0.6, 0, 0.6] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: 'easeOut' }}
          style={{ transformOrigin: `${epicenter.x}px ${epicenter.y}px` }}
        />
        <circle
          cx={epicenter.x}
          cy={epicenter.y}
          r={28}
          fill="var(--red)"
          stroke="var(--gold)"
          strokeWidth={2}
          filter="url(#epicenterGlow)"
        />
        <text
          x={epicenter.x}
          y={epicenter.y + 5}
          textAnchor="middle"
          fontSize={16}
          fontFamily="var(--font-display)"
          fontStyle="italic"
          fontWeight={700}
          fill="var(--sand)"
        >
          {sourceInitial(source.name ?? source.orgnr)}
        </text>
        <text
          x={epicenter.x}
          y={epicenter.y + 50}
          textAnchor="middle"
          fontSize={11}
          fontFamily="var(--font-ui)"
          fill="var(--sand)"
          fontWeight={600}
          letterSpacing="0.06em"
          style={{ paintOrder: 'stroke', stroke: 'var(--void)', strokeWidth: 4 }}
        >
          {source.name ? truncateName(source.name, 28) : source.orgnr}
        </text>
      </motion.g>
    </svg>
  );
}

/* ── Bottom summary strip ─────────────────────────────────────────────────── */

function BlastSummary({ data }: { data: ContagionMap }) {
  const summary = data.summary;
  return (
    <motion.footer
      className="blast-summary"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: TIMING.summaryStart / 1000, ease: EASE_OUT_EXPO }}
    >
      <SummaryStat label="Identifierade partners" value={`${summary.total_peers}`} />
      <SummaryStat
        label="Kritiska"
        value={`${summary.critical_peers}`}
        accent={summary.critical_peers > 0 ? 'var(--red)' : undefined}
      />
      <SummaryStat
        label="Hög risk"
        value={`${summary.high_peers}`}
        accent={summary.high_peers > 0 ? 'var(--amber)' : undefined}
      />
      <SummaryStat
        label="Geografisk spridning"
        value={
          summary.geographic_spread === 'municipality'
            ? 'En kommun'
            : summary.geographic_spread === 'county'
            ? 'Inom län'
            : summary.geographic_spread === 'region'
            ? 'Flera län'
            : '—'
        }
      />
      <div className="rings-legend">
        {data.rings.map((r) => (
          <span key={r.match_reason} className="ring-chip">
            <span className="ring-num">Ring {r.ring}</span>
            <span className="ring-label">
              {MATCH_REASON_LABEL_SV[r.match_reason] ?? r.match_reason}
            </span>
            <span className="ring-count">· {r.peers.length}</span>
          </span>
        ))}
      </div>
      <style>{`
        .blast-summary {
          padding: 18px 24px;
          border-top: 1px solid var(--border);
          display: flex;
          gap: 36px;
          flex-wrap: wrap;
          align-items: center;
        }
        .rings-legend {
          margin-left: auto;
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
        }
        .ring-chip {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 4px 10px;
          border: 1px solid var(--border-2);
          border-radius: 2px;
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--sand-2);
        }
        .ring-num   { color: var(--sand); letter-spacing: 0.06em; }
        .ring-label { color: var(--muted); }
        .ring-count { color: var(--muted-2); }
      `}</style>
    </motion.footer>
  );
}

function SummaryStat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value" style={accent ? { color: accent } : undefined}>
        {value}
      </span>
      <style>{`
        .stat {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .stat-label {
          font-family: var(--font-ui);
          font-size: 9px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          color: var(--muted);
          font-weight: 500;
        }
        .stat-value {
          font-family: var(--font-mono);
          font-size: 16px;
          color: var(--sand);
        }
      `}</style>
    </div>
  );
}

/* ── Empty / fallback state ───────────────────────────────────────────────── */

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="blast empty">
      <header className="blast-header">
        <span className="uppercase-label">Leveranskedjans blast radius</span>
      </header>
      <div className="empty-body">
        <div className="empty-title">{title}</div>
        <div className="empty-detail">{detail}</div>
      </div>
      <style>{`
        .blast.empty {
          border: 1px solid var(--border-2);
          background: var(--ink);
          border-radius: 4px;
          overflow: hidden;
        }
        .empty-body {
          padding: 120px 32px;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          text-align: center;
        }
        .empty-title {
          font-family: var(--font-display);
          font-style: italic;
          font-size: 18px;
          color: var(--sand);
        }
        .empty-detail {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--muted);
          max-width: 480px;
        }
      `}</style>
    </section>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */

function computePaddedBounds(
  pts: Array<{ lat: number; lng: number }>,
  pad: number,
): L.LatLngBoundsLiteral {
  if (pts.length === 0) {
    // Sweden centroid fallback
    return [[55.0, 11.0], [69.0, 24.5]];
  }
  if (pts.length === 1) {
    // Single-point: zoom out to ~60km box around it
    const { lat, lng } = pts[0];
    const dLat = 0.4;
    const dLng = 0.8;
    return [[lat - dLat, lng - dLng], [lat + dLat, lng + dLng]];
  }
  let minLat = pts[0].lat, maxLat = pts[0].lat;
  let minLng = pts[0].lng, maxLng = pts[0].lng;
  for (const p of pts) {
    if (p.lat < minLat) minLat = p.lat;
    if (p.lat > maxLat) maxLat = p.lat;
    if (p.lng < minLng) minLng = p.lng;
    if (p.lng > maxLng) maxLng = p.lng;
  }
  const dLat = Math.max(0.2, (maxLat - minLat) * pad);
  const dLng = Math.max(0.4, (maxLng - minLng) * pad);
  return [[minLat - dLat, minLng - dLng], [maxLat + dLat, maxLng + dLng]];
}

function lineColorForTier(tier: RiskTier | null): string {
  if (tier === 'CRITICAL') return 'rgba(226, 75, 74, 0.35)';
  if (tier === 'HIGH')     return 'rgba(239, 159, 39, 0.30)';
  return 'rgba(242, 237, 228, 0.15)';
}

function ringStrokeForIdx(idx: number): string {
  if (idx === 0) return 'rgba(226, 75, 74, 0.30)';
  if (idx === 1) return 'rgba(239, 159, 39, 0.22)';
  return 'rgba(242, 237, 228, 0.10)';
}

function truncateName(name: string | null | undefined, max = 18): string {
  if (!name) return '';
  if (name.length <= max) return name;
  return name.slice(0, max - 1) + '…';
}

function sourceInitial(s: string): string {
  const trimmed = s.trim();
  if (!trimmed) return '?';
  const first = trimmed.split(/\s+/)[0];
  return first[0]?.toUpperCase() ?? '?';
}
