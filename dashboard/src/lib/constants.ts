/**
 * Design tokens + tier vocabularies + animation timings.
 * Mirrors the CSS variables in globals.css so components can branch on tier.
 */

import type { RiskTier } from './api';

// ── Tier visual identity ──────────────────────────────────────────────────────

export const TIER_COLOR: Record<RiskTier, string> = {
  HEALTHY:  'var(--teal)',
  WATCH:    'var(--teal-m)',
  ELEVATED: 'var(--sand-2)',
  HIGH:     'var(--amber)',
  CRITICAL: 'var(--red)',
};

export const TIER_NUMERAL_COLOR: Record<RiskTier, string> = {
  HEALTHY:  'var(--teal)',
  WATCH:    'var(--teal-m)',
  ELEVATED: 'var(--sand)',
  HIGH:     'var(--amber)',
  CRITICAL: 'var(--gold)',
};

export const TIER_LABEL_SV: Record<RiskTier, string> = {
  HEALTHY:  'Frisk',
  WATCH:    'Bevaka',
  ELEVATED: 'Förhöjd',
  HIGH:     'Hög risk',
  CRITICAL: 'Kritisk',
};

export const TIER_LABEL_EN: Record<RiskTier, string> = {
  HEALTHY:  'Healthy',
  WATCH:    'Watch',
  ELEVATED: 'Elevated',
  HIGH:     'High',
  CRITICAL: 'Critical',
};

// ── Animation timings (ms) ────────────────────────────────────────────────────

export const TIMING = {
  scoreCountUp: 800,
  ringExpand:   600,
  ringStagger:  80,
  ring1Start:   400,
  ring2Start:   900,
  lineTrace:    300,
  linesStart:   2000,
  summaryStart: 2400,
} as const;

export const EASE_OUT_EXPO = [0.16, 1, 0.3, 1] as const;
export const MATERIAL_EASE  = [0.4, 0, 0.2, 1] as const;

// ── Match-reason → human label (Swedish) ──────────────────────────────────────

export const MATCH_REASON_LABEL_SV: Record<string, string> = {
  same_sector_kommunkod: 'Samma sektor · samma kommun',
  same_sector_county:    'Samma sektor · samma län',
};

// ── Formatters ────────────────────────────────────────────────────────────────

const SEK_NBSP = new Intl.NumberFormat('sv-SE', { useGrouping: true });

export function formatSEK(value: number | null | undefined): string {
  if (value == null) return '—';
  if (value === 0) return '0 kr';
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)} mdkr`;
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)} MSEK`;
  }
  return `${SEK_NBSP.format(value).replace(/,/g, ' ')} kr`;
}

export function formatPercentile(p: number | null | undefined): string {
  if (p == null) return '—';
  return `${p}:e percentilen`;
}

const SV_DATE = new Intl.DateTimeFormat('sv-SE', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
});

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return SV_DATE.format(new Date(iso));
  } catch {
    return iso;
  }
}

// ── Orgnr detection (matches server.py validate_orgnr permissively) ───────────

export const ORGNR_RE = /^\d{6}-?\d{4}$/;
export const ORGNR_PREFIX_RE = /^\d[\d-]{0,10}$/;
