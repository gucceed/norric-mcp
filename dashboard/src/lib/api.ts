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

// ── JSON-RPC primitives ───────────────────────────────────────────────────────

interface JsonRpcRequest {
  jsonrpc: '2.0';
  id?: number;
  method: string;
  params?: Record<string, unknown>;
}

interface JsonRpcResponse<T = unknown> {
  jsonrpc: '2.0';
  id: number;
  result?: T;
  error?: { code: number; message: string; data?: unknown };
}

interface ToolCallResult {
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}

// ── Client ────────────────────────────────────────────────────────────────────

const MCP_PROTOCOL_VERSION = '2025-03-26';
const CLIENT_INFO = { name: 'norric-dashboard', version: '0.1.0' };

class NorricMcpError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'NorricMcpError';
  }
}

export class NorricMcpClient {
  private sessionId: string | null = null;
  private initInFlight: Promise<void> | null = null;
  private nextId = 1;

  constructor(
    private readonly baseUrl: string,
    private readonly apiKey?: string,
  ) {}

  private buildHeaders(includeSession = true): HeadersInit {
    const h: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
    };
    if (includeSession && this.sessionId) {
      h['Mcp-Session-Id'] = this.sessionId;
    }
    if (this.apiKey) {
      h['X-Norric-Key'] = this.apiKey;
    }
    return h;
  }

  /**
   * Parse the response body. FastMCP may return either application/json or
   * text/event-stream (SSE) depending on the negotiation — for our one-shot
   * tool calls it's always JSON, but we handle the SSE case defensively so
   * a single streamed chunk doesn't break the client.
   */
  private async parseBody<T>(res: Response): Promise<JsonRpcResponse<T> | null> {
    const ct = res.headers.get('content-type') ?? '';
    if (ct.includes('text/event-stream')) {
      const text = await res.text();
      // Pick the first `data: {...}` frame.
      const match = text.match(/^data:\s*(.+)$/m);
      if (!match) return null;
      return JSON.parse(match[1]) as JsonRpcResponse<T>;
    }
    if (!ct.includes('application/json')) {
      // 204 No Content is valid for notifications.
      if (res.status === 204 || res.headers.get('content-length') === '0') {
        return null;
      }
    }
    const text = await res.text();
    if (!text) return null;
    return JSON.parse(text) as JsonRpcResponse<T>;
  }

  private async initialize(): Promise<void> {
    // De-dupe concurrent initialize() calls.
    if (this.initInFlight) return this.initInFlight;
    this.initInFlight = (async () => {
      const initReq: JsonRpcRequest = {
        jsonrpc: '2.0',
        id: this.nextId++,
        method: 'initialize',
        params: {
          protocolVersion: MCP_PROTOCOL_VERSION,
          capabilities: {},
          clientInfo: CLIENT_INFO,
        },
      };

      let initRes: Response;
      try {
        initRes = await fetch(this.baseUrl, {
          method: 'POST',
          headers: this.buildHeaders(false),
          body: JSON.stringify(initReq),
        });
      } catch (e) {
        this.initInFlight = null;
        throw new NorricMcpError('Failed to reach MCP backend', e);
      }

      if (!initRes.ok) {
        this.initInFlight = null;
        throw new NorricMcpError(
          `MCP initialize failed: ${initRes.status} ${initRes.statusText}`,
        );
      }

      const sid = initRes.headers.get('Mcp-Session-Id') ?? initRes.headers.get('mcp-session-id');
      if (!sid) {
        this.initInFlight = null;
        throw new NorricMcpError('MCP initialize returned no session id');
      }
      this.sessionId = sid;

      // Drain the initialize response body — the JSON-RPC handshake reply.
      await this.parseBody(initRes).catch(() => null);

      // Per MCP spec the client MUST send notifications/initialized before
      // any tool calls. It's a notification (no `id`) so no response body.
      const notif: JsonRpcRequest = {
        jsonrpc: '2.0',
        method: 'notifications/initialized',
      };
      try {
        await fetch(this.baseUrl, {
          method: 'POST',
          headers: this.buildHeaders(true),
          body: JSON.stringify(notif),
        });
      } catch (e) {
        // Notification failure isn't fatal — tool calls will surface the real error.
        // eslint-disable-next-line no-console
        console.warn('[mcp] notifications/initialized failed', e);
      }
    })();

    try {
      await this.initInFlight;
    } finally {
      // Keep the cached sessionId; clear the in-flight marker either way.
      this.initInFlight = null;
    }
  }

  /**
   * Call an MCP tool and unwrap to the canonical Norric envelope.
   * Re-initializes once on 404 (session expired server-side).
   */
  async callTool<TData>(
    name: string,
    args: Record<string, unknown>,
  ): Promise<NorricEnvelope<TData>> {
    if (!this.sessionId) {
      await this.initialize();
    }

    const callReq: JsonRpcRequest = {
      jsonrpc: '2.0',
      id: this.nextId++,
      method: 'tools/call',
      params: { name, arguments: args },
    };

    const attempt = async (): Promise<Response> =>
      fetch(this.baseUrl, {
        method: 'POST',
        headers: this.buildHeaders(true),
        body: JSON.stringify(callReq),
      });

    let res = await attempt();
    if (res.status === 404 || res.status === 401) {
      // Session may have expired. Re-init once and retry.
      this.sessionId = null;
      await this.initialize();
      res = await attempt();
    }

    if (!res.ok) {
      throw new NorricMcpError(
        `MCP tools/call ${name} failed: ${res.status} ${res.statusText}`,
      );
    }

    const body = await this.parseBody<ToolCallResult>(res);
    if (!body) {
      throw new NorricMcpError(`MCP tools/call ${name} returned empty body`);
    }
    if (body.error) {
      throw new NorricMcpError(`MCP error: ${body.error.message}`, body.error);
    }
    const content = body.result?.content?.[0];
    if (!content || content.type !== 'text' || typeof content.text !== 'string') {
      throw new NorricMcpError(`MCP tools/call ${name} returned unexpected content shape`);
    }

    let envelope: NorricEnvelope<TData>;
    try {
      envelope = JSON.parse(content.text) as NorricEnvelope<TData>;
    } catch (e) {
      throw new NorricMcpError(`MCP tools/call ${name} returned non-JSON text`, e);
    }
    return envelope;
  }

  // ── Typed wrappers — the three tools the dashboard consumes ───────────────

  score(orgnr: string) {
    return this.callTool<ScoreIntelligence>('norric_score_v1', { orgnr });
  }

  search(q: string, limit = 10) {
    return this.callTool<SearchResponse>('norric_search_v1', { q, limit });
  }

  contagionMap(orgnr: string) {
    return this.callTool<ContagionMap>('norric_contagion_map_v1', { orgnr });
  }
}

// ── Singleton (configured from Vite env) ──────────────────────────────────────

const MCP_URL =
  (import.meta.env.VITE_MCP_URL as string | undefined) ?? '/mcp';
const API_KEY = import.meta.env.VITE_NORRIC_API_KEY as string | undefined;

export const mcp = new NorricMcpClient(MCP_URL, API_KEY);

export { NorricMcpError };
