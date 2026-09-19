"""Base Sepolia-only x402 facilitator for the Norric testnet proof."""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from x402 import x402Facilitator
from x402.mechanisms.evm import FacilitatorWeb3Signer
from x402.mechanisms.evm.exact import register_exact_evm_facilitator

NETWORK = "eip155:84532"
private_key = os.environ["EVM_PRIVATE_KEY"]
rpc_url = os.environ.get("EVM_RPC_URL", "https://sepolia.base.org")
if os.environ.get("X402_NETWORK", NETWORK) != NETWORK:
    raise RuntimeError("This facilitator is Base Sepolia-only")

signer = FacilitatorWeb3Signer(private_key=private_key, rpc_url=rpc_url)
facilitator = x402Facilitator()
register_exact_evm_facilitator(
    facilitator,
    signer,
    networks=NETWORK,
    eip6492_allowed_factories=[],
)

class PaymentRequest(BaseModel):
    paymentPayload: dict
    paymentRequirements: dict

app = FastAPI(title="Norric x402 Testnet Facilitator", version="0.1.0")

@app.get("/health")
async def health():
    return {"status": "ok", "network": NETWORK, "mode": "testnet"}

@app.get("/supported")
async def supported():
    response = facilitator.get_supported()
    return {
        "kinds": [k.model_dump(by_alias=True, exclude_none=True) for k in response.kinds],
        "extensions": response.extensions,
        "signers": response.signers,
    }

@app.post("/verify")
async def verify(request: PaymentRequest):
    try:
        from x402.schemas import PaymentRequirements, parse_payment_payload
        payload = parse_payment_payload(request.paymentPayload)
        requirements = PaymentRequirements.model_validate(request.paymentRequirements)
        response = await facilitator.verify(payload, requirements)
        return response.model_dump(by_alias=True, exclude_none=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=type(exc).__name__) from exc

@app.post("/settle")
async def settle(request: PaymentRequest):
    try:
        from x402.schemas import PaymentRequirements, parse_payment_payload
        payload = parse_payment_payload(request.paymentPayload)
        requirements = PaymentRequirements.model_validate(request.paymentRequirements)
        response = await facilitator.settle(payload, requirements)
        return response.model_dump(by_alias=True, exclude_none=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=type(exc).__name__) from exc
