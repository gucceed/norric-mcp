import { motion } from 'framer-motion';
import type { ActiveContracts, RiskTier } from '../lib/api';
import {
  TIER_COLOR,
  TIER_LABEL_SV,
  EASE_OUT_EXPO,
  formatSEK,
} from '../lib/constants';

interface Props {
  active: ActiveContracts;
  /** Source tier — used to render the strip's own tier-aware chip on aggregate */
  sourceTier: RiskTier | null;
}

/**
 * ContractsStrip — proof that the cross-signal is real.
 *
 * Reads the active_contracts block already attached to the score envelope
 * (no second query). For the demo current data this is usually empty;
 * when SIGNAL contracts get populated, this strip lights up with the
 * supplier's active municipal procurement.
 */
export function ContractsStrip({ active, sourceTier }: Props) {
  const empty = active.count === 0;

  return (
    <motion.section
      className="contracts"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE_OUT_EXPO, delay: 0.2 }}
    >
      <header className="contracts-header">
        <span className="uppercase-label">Aktiva upphandlingskontrakt</span>
        <span className="contracts-subtitle">
          {empty
            ? 'Inga aktiva kontrakt registrerade'
            : `${active.count} kontrakt · ${formatSEK(active.total_value_sek)} totalt värde`}
        </span>
      </header>

      {empty ? (
        <div className="contracts-empty">
          <span className="muted-mono">
            Bolaget finns inte i SIGNAL-registret med aktiva offentliga
            kontrakt. Cross-signal exponering avgörs av leveranskedjepartners.
          </span>
        </div>
      ) : (
        <ul className="contracts-list">
          {active.municipalities.length > 0 && (
            <li className="contracts-aggregate">
              <span className="agg-label">Kommuner</span>
              <span className="agg-cities">
                {active.municipalities.join(' · ')}
              </span>
              {sourceTier && (
                <span
                  className="tier-chip"
                  style={{ color: TIER_COLOR[sourceTier] }}
                >
                  <span className="dot" />
                  {TIER_LABEL_SV[sourceTier]}
                </span>
              )}
            </li>
          )}
        </ul>
      )}

      <style>{`
        .contracts {
          border: 1px solid var(--border);
          background: var(--ink);
          border-radius: 4px;
          padding: 22px 28px;
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .contracts-header {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .contracts-subtitle {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--sand-2);
          letter-spacing: 0.02em;
        }
        .contracts-empty {
          padding: 14px 16px;
          background: var(--ink-2);
          border: 1px dashed var(--border);
          border-radius: 2px;
        }
        .muted-mono {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--muted);
          line-height: 1.5;
        }
        .contracts-list {
          list-style: none;
          margin: 0;
          padding: 0;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .contracts-aggregate {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 12px 14px;
          background: var(--ink-2);
          border-left: 2px solid var(--amber);
          border-radius: 0 2px 2px 0;
        }
        .agg-label {
          font-family: var(--font-ui);
          font-size: 9px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          color: var(--muted);
          font-weight: 500;
          min-width: 80px;
        }
        .agg-cities {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--sand);
          letter-spacing: 0.03em;
          flex: 1;
        }
        .contracts-aggregate .tier-chip {
          margin-left: auto;
        }
      `}</style>
    </motion.section>
  );
}
