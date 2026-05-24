/**
 * Norric MCP client — typed Streamable HTTP transport.
 *
 * Two-step handshake on first use, then cached for subsequent tool calls:
 *   1. POST /mcp { method: "initialize" }   → server returns Mcp-Session-Id header
 *   2. POST /mcp { method: "notifications/initialized" } with that session id
 *   3. POST /mcp { method: "tools/call", params: { name, arguments } } per call
 *
 * Response handling: FastMCP returns the tool result wrapped as
 *   { jsonrpc, id, result: { content: [{ type: "text", text: "<json-string>" }] } }
 * — we parse the inner text and return the canonical Norric envelope
 *   { data, metadata, signals, warnings }.
 *
 * In dev: vite.config proxies /mcp → localhost:8080 (FastMCP backend).
 * In prod: set VITE_MCP_URL to the absolute backend URL.
 */

// ── Canonical Norric envelope (matches server.py's wrap()) ────────────────────

export interface NorricMetadata {
  response_id: string;
  tool: string;
  source: string | string[];
  fetched_at: string;
  confidence: number;
  cache_ttl_seconds: number;
  is_cached: boolean;
  data_as_of?: string;
}

export interface NorricEnvelope<TData> {
  data: TData;
  metadata: NorricMetadata;
  signals: unknown[];
  warnings: string[];
}

// ── Tool-specific response types (mirror server.py's data shapes exactly) ─────

export type RiskTier = 'HEALTHY' | 'WATCH' | 'ELEVATED' | 'HIGH' | 'CRITICAL';

export interface CompanyIdentity {
  orgnr: string;
  name: string | null;
  orgform: string | null;
  sni_code: string | null;
  sector: string | null;
  kommunkod: string | null;
  municipality: string | null;
  county: string | null;
  lat: number | null;
  lng: number | null;
}

export interface ScoreBlock {
  value: number | null;
  tier: RiskTier | null;
  band: number | null;
  percentile: number | null;
  delta_7d: number | null;
  trajectory: 'improving' | 'stable' | 'deteriorating' | null;
  scale: '0-20';
  polarity: 'ascending_risk';
}

export interface SignalBlock {
  restanglangd: boolean;
  betalningsforelaggande: boolean;
  konkursansokan: boolean;
  f_skatt_active: boolean;
  onset_days: number | null;
  skuld_sek: number;
}

export interface TimelineBlock {
  signal_onset_date: string | null;
  median_days_to_konkurs: number;
  days_elapsed: number | null;
  days_remaining: number | null;
  probability_12w: number | null;
}

export interface ContagionPreview {
  peer_count: number;
  critical_peers: number;
  high_peers: number;
  at_risk_contract_value_sek: number;
}

export interface ActiveContracts {
  count: number;
  total_value_sek: number;
  municipalities: string[];
}

export interface ScoreIntelligence {
  company: CompanyIdentity;
  score: ScoreBlock;
  signals: SignalBlock;
  timeline: TimelineBlock;
  contagion_preview: ContagionPreview;
  active_contracts: ActiveContracts;
  meta: {
    model_version: string;
    data_freshness: string | null;
    data_freshness_hours: number | null;
    score_source: 'live' | 'no_signals' | 'mock';
    api_version: string;
  };
}

export interface SearchResult {
  orgnr: string;
  name: string;
  risk_band: number | null;
  risk_score: number | null;
  risk_tier: RiskTier | null;
  distress_probability: number | null;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  result_count: number;
}

export interface ContagionPeer {
  orgnr: string;
  name: string | null;
  tier: RiskTier | null;
  score: number | null;
  lat: number | null;
  lng: number | null;
  kommunkod: string | null;
  municipality: string | null;
  county: string | null;
}

export interface ContagionRing {
  ring: number;
  match_reason: 'same_sector_kommunkod' | 'same_sector_county';
  proximity: number;
  label: string;
  peers: ContagionPeer[];
}

export interface ContagionMap {
  source: {
    orgnr: string;
    name: string | null;
    tier: RiskTier | null;
    score: number | null;
    lat: number | null;
    lng: number | null;
    kommunkod: string | null;
    municipality: string | null;
    county: string | null;
  } | null;
  rings: ContagionRing[];
  summary: {
    total_peers: number;
    critical_peers: number;
    high_peers: number;
    geographic_spread: 'municipality' | 'county' | 'region' | null;
  };
  warning?: string;
}

// ── Client ────────────────────────────────────────────────────────────────────

class NorricMcpError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'NorricMcpError';
  }
}

/**
 * REST transport for the Norric intelligence endpoints.
 *
 * The dashboard originally targeted the FastMCP /mcp endpoint via the
 * Streamable HTTP protocol (initialize → notifications/initialized →
 * tools/call). That worked from curl and from the MCP TypeScript SDK,
 * but every browser fetch we tried — proxied or direct, SSE or json,
 * with or without keepalive — saw the response body delayed by 20+
 * seconds despite headers arriving promptly. Root cause was never
 * conclusively isolated; suspected interaction between FastMCP's SSE
 * stream lifecycle and the browser's fetch body buffering.
 *
 * The /api/v1/* endpoints in kreditvakt/api.py wrap the same underlying
 * functions the MCP tools call (kreditvakt.intelligence) and return the
 * same Norric envelope shape. No session handshake, no SSE, content-type
 * application/json with Content-Length. The MCP tools remain canonical
 * for non-browser clients (IDE integrations, curl, MCP SDKs).
 */
export class NorricMcpClient {
  constructor(
    private readonly baseUrl: string,
    private readonly apiKey?: string,
  ) {}

  private buildHeaders(): HeadersInit {
    const h: Record<string, string> = {
      Accept: 'application/json',
    };
    if (this.apiKey) {
      h['X-Norric-Key'] = this.apiKey;
    }
    return h;
  }

  private async getJson<T>(path: string): Promise<NorricEnvelope<T>> {
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        method: 'GET',
        headers: this.buildHeaders(),
      });
    } catch (e) {
      throw new NorricMcpError('Failed to reach Norric backend', e);
    }
    if (!res.ok) {
      throw new NorricMcpError(`Norric ${path} → HTTP ${res.status} ${res.statusText}`);
    }
    return (await res.json()) as NorricEnvelope<T>;
  }

  // ── Typed wrappers — the three endpoints the dashboard consumes ──────────

  score(orgnr: string) {
    return this.getJson<ScoreIntelligence>(`/score/${encodeURIComponent(orgnr)}`);
  }

  search(q: string, limit = 10) {
    const qs = new URLSearchParams({ q, limit: String(limit) }).toString();
    return this.getJson<SearchResponse>(`/search?${qs}`);
  }

  contagionMap(orgnr: string) {
    return this.getJson<ContagionMap>(`/contagion-map/${encodeURIComponent(orgnr)}`);
  }
}

// ── Singleton (configured from Vite env) ──────────────────────────────────────

const BASE =
  (import.meta.env.VITE_NORRIC_BASE as string | undefined) ?? '/api/v1';
const API_KEY = import.meta.env.VITE_NORRIC_API_KEY as string | undefined;

export const mcp = new NorricMcpClient(BASE, API_KEY);

export { NorricMcpError };
