# x402 Base Sepolia proof

This branch gates one low-risk MCP tool, `norric_data_freshness_v1`, behind an
x402 v2 `exact` payment of 0.01 test USDC on Base Sepolia. It is disabled by
default and does not alter the other tools or the existing API-key path.

## Required environment

- `X402_TESTNET_ENABLED=true`
- `X402_NETWORK=eip155:84532` (any other network fails startup)
- `X402_PAY_TO=0x...` (public receiving address only, never a private key)
- `X402_FACILITATOR_URL=https://...` (EU-hosted facilitator)
- `X402_DATA_FRESHNESS_PRICE=$0.01`

During this proof, an API key is still required to reach the MCP endpoint. The
paid wrapper then issues the x402 challenge, verifies the retry, runs the tool
once, and settles after successful execution. This keeps every unwrapped tool
closed while replay, idempotency, invalid-signature and settlement-failure
behavior is tested. Only after the testnet proof should x402 become an
alternative to API-key authentication.

## Production hold

Mainnet is intentionally impossible in this branch. Public-chain settlement
exposes wallet addresses, asset, amount and timing outside the EU. The current
EU-only rule therefore blocks real payments until a confidential route is
approved.

Options to assess later:

1. A privacy-preserving EVM/L2 with stablecoin support and an x402 v2 mechanism,
   provided payment metadata is confidential and the facilitator/RPC remain EU-hosted.
2. A permissioned EVM network operated in the EU, with a euro or dollar
   stablecoin and a custom x402 mechanism/facilitator.
3. Off-chain payment channels or batched settlement that hide individual calls.
   Batching improves linkability but is not confidential if amounts and wallets
   remain public.
4. Keep prepaid enterprise API keys until a confidential settlement rail meets
   the residency rule.

No mainnet path should be enabled based only on marketing claims. Verify the
ledger visibility, validator geography, RPC logs, facilitator logs, sanctions
screening, custody and accounting treatment first.

## Wallet-only MCP entry path

Anonymous clients may initialize an MCP session, list tools, call the free
`norric_status_v1` tool, and call the payment-gated
`norric_data_freshness_v1` tool. Every other anonymous `tools/call` is rejected
before FastMCP dispatch. The paid tool still challenges, verifies, executes once,
and settles through x402. API-key sessions retain access to the full tool set.

The anonymous paid path is Base Sepolia-only and inherits the hard mainnet block.
As a simple abuse/spend sanity bound, a verified payer wallet may execute at most
30 paid calls per process-hour. This is intentionally conservative for the
proof: the payment itself provides the primary economic abuse control, while the
bounded in-memory limiter prevents accidental rapid spend. A production-scale
version should move the counter to the existing EU-hosted Redis service so the
limit is shared across replicas.

## Approved agent price bands

Exact Base Sepolia prices are configured as atomic test USDC: lookup 2,000;
signal 5,000; evidence 10,000; feed/batch 20,000; heavy synthesis 50,000.
Tool assignments are data in `TOOL_PRICE_BANDS`. This change wires only
`kreditvakt_score_company_v1`, the lightest live company score lookup, to the
lookup band. Discovery, `norric_status_v1`, and `norric_data_freshness_v1` are
free. Watchlist/event metering remains out of scope.
