import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  mcp,
  type SearchResult,
  type NorricEnvelope,
  type SearchResponse,
  type RiskTier,
} from '../lib/api';
import {
  TIER_COLOR,
  TIER_LABEL_SV,
  ORGNR_RE,
  ORGNR_PREFIX_RE,
} from '../lib/constants';

interface Props {
  autoFocus?: boolean;
  compact?: boolean;
  initialValue?: string;
  onSelect: (orgnr: string) => void;
}

const DEBOUNCE_MS = 200;

export function SearchBar({ autoFocus, compact, initialValue, onSelect }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(initialValue ?? '');
  const [debounced, setDebounced] = useState(value);
  const [activeIdx, setActiveIdx] = useState(0);
  const [isFocused, setIsFocused] = useState(false);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value.trim()), DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [value]);

  const isOrgnrShape = useMemo(
    () => ORGNR_PREFIX_RE.test(debounced.replace(/\s/g, '')),
    [debounced],
  );

  // Only run the search when the user is actively typing in a focused input.
  // Without `isFocused` gating, the pre-filled compact bar on /score/:orgnr
  // would fire a search on every mount — piling up onto the already-running
  // score + contagion tool calls and forcing serial queuing in the MCP
  // session. We also skip when the value matches the navigated orgnr exactly.
  const skipForUrlMatch = compact && debounced === (initialValue ?? '');
  const q = useQuery<NorricEnvelope<SearchResponse>>({
    queryKey: ['search', debounced],
    queryFn: () => mcp.search(debounced, 8),
    enabled: isFocused && debounced.length >= 2 && !skipForUrlMatch,
    staleTime: 30_000,
  });

  const results: SearchResult[] = q.data?.data.results ?? [];
  const showDropdown = isFocused && debounced.length >= 2 && (results.length > 0 || q.isPending);

  useEffect(() => setActiveIdx(0), [debounced]);

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, Math.max(0, results.length - 1)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const cleaned = value.replace(/\s/g, '');
      if (ORGNR_RE.test(cleaned)) {
        // Normalize to dashed canonical form before navigating.
        const c = cleaned.replace('-', '');
        onSelect(`${c.slice(0, 6)}-${c.slice(6)}`);
        return;
      }
      if (results[activeIdx]) {
        onSelect(results[activeIdx].orgnr);
      }
    } else if (e.key === 'Escape') {
      inputRef.current?.blur();
    }
  }

  return (
    <div className={`search ${compact ? 'compact' : ''}`}>
      <div className="search-line">
        <input
          ref={inputRef}
          type="text"
          inputMode="search"
          placeholder="Organisationsnummer eller företagsnamn"
          aria-label="Sök företag"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => window.setTimeout(() => setIsFocused(false), 150)}
          onKeyDown={handleKey}
          autoComplete="off"
          spellCheck={false}
        />
        <span className="search-arrow" aria-hidden>→</span>
      </div>

      {showDropdown && (
        <div className="search-dropdown" role="listbox">
          {q.isPending && (
            <div className="search-empty">Söker…</div>
          )}
          {!q.isPending &&
            results.map((r, i) => (
              <SearchRow
                key={r.orgnr}
                row={r}
                active={i === activeIdx}
                onSelect={() => onSelect(r.orgnr)}
                onHover={() => setActiveIdx(i)}
              />
            ))}
          {!q.isPending && results.length === 0 && debounced.length >= 2 && (
            <div className="search-empty">Inga träffar för «{debounced}»</div>
          )}
        </div>
      )}

      {!compact && !showDropdown && isOrgnrShape && debounced.length > 0 && (
        <div className="search-hint">
          Tryck Enter för att slå upp <span className="hint-orgnr">{debounced}</span>
        </div>
      )}

      <style>{`
        .search {
          position: relative;
          width: 100%;
          max-width: 560px;
        }
        .search.compact { max-width: 720px; }

        .search-line {
          display: flex;
          align-items: center;
          gap: 12px;
          border-bottom: 1px solid var(--border-2);
          padding: 12px 4px;
          transition: border-color 200ms;
        }
        .search-line:focus-within { border-color: var(--sand-2); }

        .search input {
          flex: 1;
          font-family: var(--font-mono);
          font-size: 18px;
          letter-spacing: 0.03em;
          color: var(--sand);
        }
        .search.compact input { font-size: 14px; }
        .search input::placeholder { color: var(--muted-2); }

        .search-arrow {
          font-family: var(--font-mono);
          color: var(--muted);
          font-size: 16px;
          padding-right: 4px;
        }

        .search-dropdown {
          position: absolute;
          top: calc(100% + 4px);
          left: 0;
          right: 0;
          background: var(--ink-2);
          border: 1px solid var(--border-2);
          border-radius: 4px;
          overflow: hidden;
          z-index: 30;
          max-height: 380px;
          overflow-y: auto;
        }
        .search-empty {
          padding: 14px 16px;
          font-family: var(--font-mono);
          color: var(--muted);
          font-size: 12px;
        }
        .search-hint {
          margin-top: 12px;
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--muted);
        }
        .hint-orgnr { color: var(--sand-2); }
      `}</style>
    </div>
  );
}

function SearchRow({
  row,
  active,
  onSelect,
  onHover,
}: {
  row: SearchResult;
  active: boolean;
  onSelect: () => void;
  onHover: () => void;
}) {
  const tier = row.risk_tier as RiskTier | null;
  return (
    <button
      role="option"
      aria-selected={active}
      className={`search-row ${active ? 'active' : ''}`}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onSelect}
      onMouseEnter={onHover}
    >
      <div className="row-main">
        <div className="row-name">{row.name}</div>
        <div className="row-orgnr">{row.orgnr}</div>
      </div>
      <div className="row-right">
        {tier ? (
          <span className="row-tier" style={{ color: TIER_COLOR[tier] }}>
            <span className="row-tier-dot" />
            {TIER_LABEL_SV[tier]}
          </span>
        ) : (
          <span className="row-tier muted">—</span>
        )}
      </div>
      <style>{`
        .search-row {
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          text-align: left;
          border-bottom: 1px solid var(--border);
          transition: background-color 100ms;
        }
        .search-row:last-child { border-bottom: none; }
        .search-row.active { background: var(--ink-3); }

        .row-main {
          display: flex;
          flex-direction: column;
          gap: 4px;
          min-width: 0;
        }
        .row-name {
          font-family: var(--font-ui);
          font-size: 13px;
          font-weight: 500;
          color: var(--sand);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .row-orgnr {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--muted);
          letter-spacing: 0.03em;
        }

        .row-right { flex-shrink: 0; padding-left: 16px; }
        .row-tier {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-family: var(--font-ui);
          font-size: 10px;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          font-weight: 600;
        }
        .row-tier.muted { color: var(--muted-2); }
        .row-tier-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: currentColor;
        }
      `}</style>
    </button>
  );
}
