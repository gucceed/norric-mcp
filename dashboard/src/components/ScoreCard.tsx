import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  type NorricEnvelope,
  type ScoreIntelligence,
  type RiskTier,
} from '../lib/api';
import {
  TIER_COLOR,
  TIER_LABEL_SV,
  TIER_NUMERAL_COLOR,
  TIMING,
  EASE_OUT_EXPO,
  formatSEK,
  formatPercentile,
} from '../lib/constants';
import { SignalGrid } from './SignalGrid';
import { TimelineArc } from './TimelineArc';

interface Props {
  envelope: NorricEnvelope<ScoreIntelligence>;
}

export function ScoreCard({ envelope }: Props) {
  const { data, warnings } = envelope;
  const { company, score, signals, timeline, contagion_preview } = data;
  const tier = score.tier as RiskTier | null;

  return (
    <article className="score-card">
      <header className="score-header">
        <div className="header-left">
          <h1 className="company-name">{company.name ?? company.orgnr}</h1>
          <div className="company-meta">
            <span className="orgnr">{company.orgnr}</span>
            {company.sector && (
              <>
                <span className="sep">·</span>
                <span>{company.sector}</span>
              </>
            )}
            {company.municipality && (
              <>
                <span className="sep">·</span>
                <span>{company.municipality}</span>
              </>
            )}
            {company.county && company.county !== company.municipality && (
              <>
                <span className="sep">·</span>
                <span className="muted">{company.county} län</span>
              </>
            )}
          </div>
        </div>

        <div className="header-right">
          <ScoreNumeral value={score.value} tier={tier} />
          <TierBadge tier={tier} delta={score.delta_7d} percentile={score.percentile} />
        </div>
      </header>

      <hr className="divider" />

      <div className="score-body">
        <TimelineArc timeline={timeline} />
        <SignalGrid signals={signals} />
      </div>

      <hr className="divider" />

      <footer className="score-footer">
        <ContagionSummaryRow preview={contagion_preview} />
        {data.meta.score_source === 'no_signals' && (
          <div className="score-note">
            <span className="uppercase-label">Status</span>
            <span>
              Bolaget finns i Norrics universe men har inga aktiva signaler just nu.
              Riskvärdena visas som «—».
            </span>
          </div>
        )}
        {warnings.length > 0 && (
          <ul className="warnings">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </footer>

      <style>{`
        .score-card {
          border: 1px solid var(--border-2);
          background: linear-gradient(180deg, var(--ink-2), var(--ink) 60%);
          border-radius: 4px;
          padding: 36px 40px 28px;
        }

        .score-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 32px;
        }
        .header-left { min-width: 0; flex: 1; }
        .header-right {
          display: flex;
          align-items: center;
          gap: 24px;
          flex-shrink: 0;
        }

        .company-name {
          font-family: var(--font-display);
          font-style: italic;
          font-weight: 600;
          font-size: 28px;
          letter-spacing: -0.02em;
          margin: 0;
          color: var(--sand);
          line-height: 1.1;
        }
        .company-meta {
          margin-top: 10px;
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--sand-2);
          letter-spacing: 0.03em;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          align-items: center;
        }
        .company-meta .orgnr { color: var(--sand); }
        .company-meta .sep   { color: var(--muted-2); }
        .company-meta .muted { color: var(--muted); }

        .score-body {
          display: grid;
          grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr);
          gap: 40px;
          padding: 28px 0;
          align-items: flex-start;
        }

        .score-footer {
          padding-top: 18px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .score-note {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--muted);
          display: flex;
          gap: 12px;
          align-items: baseline;
        }
        .warnings {
          margin: 0;
          padding: 0;
          list-style: none;
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--muted-2);
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .warnings li::before {
          content: '! ';
          color: var(--amber);
          font-weight: 600;
        }

        @media (max-width: 860px) {
          .score-body { grid-template-columns: 1fr; gap: 32px; }
        }
      `}</style>
    </article>
  );
}

/* ── 96px italic Fraunces numeral with count-up animation ──────────────────── */

function ScoreNumeral({
  value,
  tier,
}: {
  value: number | null;
  tier: RiskTier | null;
}) {
  const [displayed, setDisplayed] = useState(0);
  useEffect(() => {
    if (value == null) {
      setDisplayed(0);
      return;
    }
    const start = performance.now();
    const duration = TIMING.scoreCountUp;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / duration);
      // ease out expo
      const eased = 1 - Math.pow(2, -10 * k);
      setDisplayed(Math.round(eased * value));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  if (value == null) {
    return (
      <div className="score-numeral muted" aria-label="ingen poäng">
        <span className="num">—</span>
        <style>{numeralCss(null)}</style>
      </div>
    );
  }

  return (
    <motion.div
      className="score-numeral"
      style={{ color: tier ? TIER_NUMERAL_COLOR[tier] : 'var(--sand)' }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: EASE_OUT_EXPO }}
      aria-label={`Riskpoäng ${value} av 20`}
    >
      <span className="num">{displayed}</span>
      <span className="scale">/20</span>
      <style>{numeralCss(tier)}</style>
    </motion.div>
  );
}

function numeralCss(_tier: RiskTier | null) {
  return `
    .score-numeral {
      display: flex;
      align-items: baseline;
      gap: 8px;
      line-height: 1;
    }
    .score-numeral .num {
      font-family: var(--font-display);
      font-style: italic;
      font-weight: 700;
      font-size: 96px;
      letter-spacing: -0.04em;
      line-height: 1;
      font-variation-settings: 'opsz' 144;
    }
    .score-numeral .scale {
      font-family: var(--font-mono);
      font-size: 14px;
      color: var(--muted);
      letter-spacing: 0.06em;
    }
    .score-numeral.muted .num { color: var(--muted-2); }
  `;
}

/* ── Tier badge + delta + percentile ───────────────────────────────────────── */

function TierBadge({
  tier,
  delta,
  percentile,
}: {
  tier: RiskTier | null;
  delta: number | null;
  percentile: number | null;
}) {
  return (
    <div className="badge-stack">
      <span
        className="tier-chip"
        style={{ color: tier ? TIER_COLOR[tier] : 'var(--muted-2)' }}
      >
        <span className="dot" />
        {tier ? TIER_LABEL_SV[tier] : 'OKÄND'}
      </span>
      <div className="meta-line">
        <DeltaIndicator delta={delta} />
        <span className="percentile">{formatPercentile(percentile)}</span>
      </div>
      <style>{`
        .badge-stack {
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 10px;
        }
        .meta-line {
          display: flex;
          align-items: center;
          gap: 12px;
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--muted);
          letter-spacing: 0.03em;
        }
        .percentile { white-space: nowrap; }
      `}</style>
    </div>
  );
}

function DeltaIndicator({ delta }: { delta: number | null }) {
  if (delta == null) return null;
  if (delta === 0) {
    return <span className="delta" style={{ color: 'var(--muted)' }}>→ stabil</span>;
  }
  const worsening = delta > 0;
  return (
    <span
      className="delta"
      style={{ color: worsening ? 'var(--red)' : 'var(--teal-m)' }}
    >
      {worsening ? '↑' : '↓'} {Math.abs(delta)} band 7d
    </span>
  );
}

/* ── Contagion preview row inside the score card ──────────────────────────── */

function ContagionSummaryRow({ preview }: { preview: ScoreIntelligence['contagion_preview'] }) {
  if (preview.peer_count === 0) {
    return (
      <div className="contagion-summary empty">
        <span className="uppercase-label">Leveranskedjeexponering</span>
        <span className="muted-text">Inga identifierade leverantörspartners idag</span>
      </div>
    );
  }
  return (
    <div className="contagion-summary">
      <span className="uppercase-label">Leveranskedjeexponering</span>
      <div className="summary-row">
        <Metric label="Partners" value={`${preview.peer_count}`} />
        {preview.critical_peers > 0 && (
          <Metric label="Kritiska" value={`${preview.critical_peers}`} accent="var(--red)" />
        )}
        {preview.high_peers > 0 && (
          <Metric label="Hög risk" value={`${preview.high_peers}`} accent="var(--amber)" />
        )}
        {preview.at_risk_contract_value_sek > 0 && (
          <Metric
            label="Värde i risk"
            value={formatSEK(preview.at_risk_contract_value_sek)}
          />
        )}
      </div>
      <style>{`
        .contagion-summary {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .contagion-summary.empty {
          flex-direction: row;
          align-items: baseline;
          gap: 14px;
        }
        .contagion-summary .muted-text {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--muted);
        }
        .summary-row {
          display: flex;
          gap: 36px;
          flex-wrap: wrap;
        }
      `}</style>
    </div>
  );
}

function Metric({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value" style={accent ? { color: accent } : undefined}>
        {value}
      </span>
      <style>{`
        .metric {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .metric-label {
          font-family: var(--font-ui);
          font-size: 9px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          color: var(--muted);
          font-weight: 500;
        }
        .metric-value {
          font-family: var(--font-mono);
          font-size: 18px;
          color: var(--sand);
          letter-spacing: 0.02em;
        }
      `}</style>
    </div>
  );
}
