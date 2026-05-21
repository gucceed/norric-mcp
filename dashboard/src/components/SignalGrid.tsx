import { motion } from 'framer-motion';
import type { SignalBlock } from '../lib/api';
import { formatSEK, EASE_OUT_EXPO } from '../lib/constants';

interface Props {
  signals: SignalBlock;
}

interface FlagRow {
  key: keyof SignalBlock | 'f_skatt';
  label: string;
  active: boolean;
  /** Active state can be alarming or neutral; F-skatt revoked is alarming. */
  tone: 'normal' | 'alarming';
  detail?: string | null;
}

export function SignalGrid({ signals }: Props) {
  const rows: FlagRow[] = [
    {
      key:    'restanglangd',
      label:  'Restanslängd',
      active: signals.restanglangd,
      tone:   signals.restanglangd ? 'alarming' : 'normal',
      detail: signals.restanglangd && signals.skuld_sek
        ? `${formatSEK(signals.skuld_sek)} obetald skatt`
        : null,
    },
    {
      key:    'betalningsforelaggande',
      label:  'Betalningsförelägganden',
      active: signals.betalningsforelaggande,
      tone:   signals.betalningsforelaggande ? 'alarming' : 'normal',
      detail: signals.betalningsforelaggande
        ? 'Aktiva mål i Kronofogden'
        : null,
    },
    {
      key:    'konkursansokan',
      label:  'Konkursansökan',
      active: signals.konkursansokan,
      tone:   signals.konkursansokan ? 'alarming' : 'normal',
      detail: signals.konkursansokan
        ? 'Bolagsverket — konkurs inledd'
        : null,
    },
    {
      // f_skatt is positive when active; F-skatt **revoked** is the alarm.
      key:    'f_skatt',
      label:  'F-skatt',
      active: signals.f_skatt_active,
      tone:   signals.f_skatt_active ? 'normal' : 'alarming',
      detail: signals.f_skatt_active ? 'Aktiv' : 'Återkallad eller saknas',
    },
  ];

  return (
    <div className="signal-grid">
      <div className="uppercase-label">Signaler</div>
      <ul className="signal-rows">
        {rows.map((r, i) => (
          <motion.li
            key={r.key as string}
            className={`signal-row ${r.active ? 'active' : 'inactive'} ${r.tone}`}
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{
              duration: 0.4,
              ease: EASE_OUT_EXPO,
              delay: 0.2 + i * 0.08,
            }}
          >
            <span className="dot" aria-hidden />
            <span className="label">{r.label}</span>
            <span className="state">
              {r.active ? (r.tone === 'alarming' ? 'AKTIV' : 'AKTIV')
                       : (r.tone === 'alarming' ? 'ÅTERKALLAD' : 'ej aktiv')}
            </span>
            {r.detail && <span className="detail">{r.detail}</span>}
          </motion.li>
        ))}
      </ul>

      <style>{`
        .signal-grid {
          display: flex;
          flex-direction: column;
          gap: 14px;
          min-width: 280px;
        }
        .signal-rows {
          list-style: none;
          margin: 0;
          padding: 0;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .signal-row {
          display: grid;
          grid-template-columns: 10px 1fr auto;
          grid-template-rows: auto auto;
          align-items: center;
          gap: 4px 12px;
          padding-bottom: 12px;
          border-bottom: 1px dashed var(--border);
        }
        .signal-row:last-child { border-bottom: none; }

        .dot {
          grid-row: 1 / 2;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--muted-2);
        }
        .signal-row.active.alarming .dot { background: var(--red);   box-shadow: 0 0 8px var(--red-pulse); }
        .signal-row.active.normal   .dot { background: var(--teal); }
        .signal-row.inactive.alarming .dot { background: var(--amber); }

        .label {
          font-family: var(--font-ui);
          font-size: 12px;
          color: var(--sand);
          font-weight: 500;
        }
        .signal-row.inactive .label { color: var(--sand-2); }

        .state {
          font-family: var(--font-mono);
          font-size: 10px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: var(--muted);
        }
        .signal-row.active.alarming    .state { color: var(--red); }
        .signal-row.active.normal      .state { color: var(--teal-m); }
        .signal-row.inactive.alarming  .state { color: var(--amber); }

        .detail {
          grid-column: 2 / -1;
          grid-row: 2 / 3;
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--muted);
          letter-spacing: 0.02em;
        }
      `}</style>
    </div>
  );
}
