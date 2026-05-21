import { Routes, Route, useNavigate, useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { SearchBar } from './components/SearchBar';
import { ScoreCard } from './components/ScoreCard';
import { BlastRadius } from './components/BlastRadius';
import { ContractsStrip } from './components/ContractsStrip';
import { mcp, type ScoreIntelligence, type ContagionMap, type NorricEnvelope } from './lib/api';

export default function App() {
  const navigate = useNavigate();

  return (
    <div className="app">
      <Header />
      <Routes>
        <Route
          path="/"
          element={
            <main className="home">
              <div className="brand">
                <div className="brand-mark">NORRIC INTELLIGENCE</div>
                <div className="brand-sub">Privat epistemisk infrastruktur · Sverige</div>
              </div>
              <SearchBar
                autoFocus
                onSelect={(orgnr) => navigate(`/score/${orgnr}`)}
              />
            </main>
          }
        />
        <Route path="/score/:orgnr" element={<ScoreScreen />} />
      </Routes>
      <style>{`
        .app {
          min-height: 100vh;
          display: flex;
          flex-direction: column;
        }
        .home {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 60px 24px;
          gap: 56px;
        }
        .brand {
          text-align: center;
        }
        .brand-mark {
          font-family: var(--font-ui);
          font-size: 12px;
          letter-spacing: 0.32em;
          font-weight: 600;
          color: var(--sand);
        }
        .brand-sub {
          margin-top: 12px;
          font-family: var(--font-mono);
          font-size: 11px;
          letter-spacing: 0.06em;
          color: var(--muted);
        }
      `}</style>
    </div>
  );
}

function Header() {
  return (
    <header className="header">
      <Link to="/" className="logo">
        <span className="logo-mark">N</span>
        <span className="logo-text">NORRIC</span>
      </Link>
      <style>{`
        .header {
          padding: 18px 28px;
          border-bottom: 1px solid var(--border);
          display: flex;
          align-items: center;
        }
        .logo {
          display: inline-flex;
          align-items: center;
          gap: 10px;
        }
        .logo-mark {
          width: 24px;
          height: 24px;
          border-radius: 2px;
          background: var(--sand);
          color: var(--void);
          font-family: var(--font-display);
          font-style: italic;
          font-weight: 700;
          display: grid;
          place-items: center;
          font-size: 14px;
        }
        .logo-text {
          font-family: var(--font-ui);
          font-size: 11px;
          letter-spacing: 0.28em;
          color: var(--sand);
          font-weight: 600;
        }
      `}</style>
    </header>
  );
}

function ScoreScreen() {
  const { orgnr = '' } = useParams<{ orgnr: string }>();
  const navigate = useNavigate();

  const scoreQ = useQuery<NorricEnvelope<ScoreIntelligence>>({
    queryKey: ['score', orgnr],
    queryFn: () => mcp.score(orgnr),
    enabled: !!orgnr,
  });

  const contagionQ = useQuery<NorricEnvelope<ContagionMap>>({
    queryKey: ['contagion-map', orgnr],
    queryFn: () => mcp.contagionMap(orgnr),
    enabled: !!orgnr,
  });

  return (
    <main className="score-screen">
      <SearchBar
        compact
        initialValue={orgnr}
        onSelect={(o) => navigate(`/score/${o}`)}
      />

      <section className="score-screen-section">
        {scoreQ.isPending && <SkeletonCard />}
        {scoreQ.isError && (
          <ErrorPanel
            title="Kunde inte hämta poäng"
            detail={(scoreQ.error as Error)?.message ?? 'okänt fel'}
          />
        )}
        {scoreQ.data && <ScoreCard envelope={scoreQ.data} />}
      </section>

      <section className="score-screen-section">
        {contagionQ.isPending && <SkeletonBlast />}
        {contagionQ.isError && (
          <ErrorPanel
            title="Kunde inte hämta blast radius"
            detail={(contagionQ.error as Error)?.message ?? 'okänt fel'}
          />
        )}
        {contagionQ.data && <BlastRadius envelope={contagionQ.data} />}
      </section>

      <section className="score-screen-section contracts-section">
        {scoreQ.data && (
          <ContractsStrip
            active={scoreQ.data.data.active_contracts}
            sourceTier={scoreQ.data.data.score.tier}
          />
        )}
      </section>

      <style>{`
        .score-screen {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 32px 24px 96px;
          gap: 40px;
        }
        .score-screen-section {
          width: 100%;
          max-width: 1100px;
        }
        .contracts-section {
          margin-top: 8px;
        }
      `}</style>
    </main>
  );
}

function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <div className="skel-row skel-big" />
      <div className="skel-row" style={{ width: '60%' }} />
      <div className="skel-row" style={{ width: '40%' }} />
      <style>{`
        .skeleton-card {
          border: 1px solid var(--border);
          background: var(--ink);
          padding: 48px;
          border-radius: 4px;
          display: flex;
          flex-direction: column;
          gap: 16px;
          min-height: 280px;
        }
        .skel-row {
          height: 14px;
          background: var(--ink-2);
          border-radius: 2px;
          animation: pulse 1.6s ease-in-out infinite;
          width: 80%;
        }
        .skel-big { height: 64px; width: 30%; }
        @keyframes pulse {
          0%, 100% { opacity: 0.6; }
          50%      { opacity: 1; }
        }
      `}</style>
    </div>
  );
}

function SkeletonBlast() {
  return (
    <div className="skeleton-blast">
      <div className="skel-orb" />
      <div className="uppercase-label">Beräknar leveranskedjeradius…</div>
      <style>{`
        .skeleton-blast {
          height: 480px;
          display: grid;
          place-items: center;
          border: 1px solid var(--border);
          background: var(--ink);
          border-radius: 4px;
          gap: 16px;
        }
        .skel-orb {
          width: 60px;
          height: 60px;
          border-radius: 50%;
          background: var(--red-l);
          box-shadow: 0 0 0 0 var(--red-pulse);
          animation: orb 2s ease-out infinite;
        }
        @keyframes orb {
          0%   { box-shadow: 0 0 0 0   var(--red-pulse); }
          70%  { box-shadow: 0 0 0 28px rgba(226,75,74,0); }
          100% { box-shadow: 0 0 0 0   rgba(226,75,74,0); }
        }
      `}</style>
    </div>
  );
}

function ErrorPanel({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="error-panel">
      <div className="error-title">{title}</div>
      <div className="error-detail">{detail}</div>
      <style>{`
        .error-panel {
          border: 1px solid var(--border-2);
          background: var(--red-l);
          color: var(--sand);
          padding: 24px;
          border-radius: 4px;
        }
        .error-title {
          font-family: var(--font-ui);
          font-size: 11px;
          letter-spacing: 0.2em;
          text-transform: uppercase;
          color: var(--red);
          margin-bottom: 8px;
        }
        .error-detail {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--sand-2);
        }
      `}</style>
    </div>
  );
}
