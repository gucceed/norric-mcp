import pytest

from x402_payments import (
    BASE_SEPOLIA,
    X402ConfigurationError,
    build_data_freshness_wrapper,
    validate_testnet_config,
)


def test_disabled_gate_is_noop():
    async def handler():
        return {"ok": True}

    wrapped = build_data_freshness_wrapper({})(handler)
    assert wrapped is handler


def test_valid_base_sepolia_config():
    config = validate_testnet_config({
        "X402_NETWORK": BASE_SEPOLIA,
        "X402_PAY_TO": "0x" + "1" * 40,
        "X402_FACILITATOR_URL": "https://facilitator.eu.example",
    })
    assert config == {
        "network": BASE_SEPOLIA,
        "pay_to": "0x" + "1" * 40,
        "facilitator_url": "https://facilitator.eu.example",
    }


def test_mainnet_is_refused():
    with pytest.raises(X402ConfigurationError, match="Base Sepolia only"):
        validate_testnet_config({
            "X402_NETWORK": "eip155:8453",
            "X402_PAY_TO": "0x" + "1" * 40,
            "X402_FACILITATOR_URL": "https://facilitator.eu.example",
        })


@pytest.mark.parametrize("url", ["", "http://facilitator.eu.example"])
def test_missing_or_insecure_facilitator_is_refused(url):
    with pytest.raises(X402ConfigurationError):
        validate_testnet_config({
            "X402_NETWORK": BASE_SEPOLIA,
            "X402_PAY_TO": "0x" + "1" * 40,
            "X402_FACILITATOR_URL": url,
        })


def test_enabled_gate_builds_exact_sepolia_requirement(monkeypatch):
    from types import SimpleNamespace
    import x402_payments

    captured = {}

    class FakeFacilitator:
        def __init__(self, config):
            captured["facilitator"] = config

    class FakeServer:
        def __init__(self, facilitator):
            captured["server_facilitator"] = facilitator

        def register(self, network, scheme):
            captured["registered"] = network

        def initialize(self):
            captured["initialized"] = True

        def build_payment_requirements(self, config):
            captured["resource_config"] = config
            return ["requirement"]

    async def sentinel(**kwargs):
        return kwargs

    def fake_wrapper(server, *, accepts, resource, hooks):
        captured["accepts"] = accepts
        captured["resource"] = resource
        captured["hooks"] = hooks
        return lambda handler: sentinel

    monkeypatch.setattr("x402.http.HTTPFacilitatorClient", FakeFacilitator)
    monkeypatch.setattr("x402.x402ResourceServer", FakeServer)
    monkeypatch.setattr("x402.mcp.create_payment_wrapper", fake_wrapper)

    wrapper = x402_payments.build_tool_payment_wrapper("kreditvakt_score_company_v1", {
        "X402_TESTNET_ENABLED": "true",
        "X402_NETWORK": BASE_SEPOLIA,
        "X402_PAY_TO": "0x" + "1" * 40,
        "X402_FACILITATOR_URL": "https://facilitator.eu.example",
    })
    wrapped = wrapper(lambda: None)
    assert wrapped.__wrapped__ is sentinel
    assert captured["facilitator"] == {"url": "https://facilitator.eu.example"}
    assert captured["registered"] == BASE_SEPOLIA
    assert captured["initialized"] is True
    assert captured["resource_config"].network == BASE_SEPOLIA
    assert captured["resource_config"].pay_to == "0x" + "1" * 40
    assert captured["resource_config"].price.amount == "2000"
    assert captured["resource_config"].price.asset == x402_payments.BASE_SEPOLIA_USDC
    assert captured["resource_config"].price.asset.startswith("0x")
    assert len(captured["resource_config"].price.asset) == 42
    assert captured["resource_config"].max_timeout_seconds == 120
    assert captured["accepts"] == ["requirement"]


def test_per_wallet_execution_limit_is_bounded():
    import x402_payments
    from types import SimpleNamespace

    x402_payments._wallet_calls.clear()
    payment = SimpleNamespace(payload={"authorization": {"from": "0xAbC"}})
    for _ in range(x402_payments._WALLET_MAX_CALLS_PER_WINDOW):
        assert x402_payments._allow_wallet_payment(payment, now=1000)
    assert not x402_payments._allow_wallet_payment(payment, now=1000)
    assert x402_payments._allow_wallet_payment(
        payment, now=1000 + x402_payments._WALLET_WINDOW_SECONDS + 1
    )


def test_payment_without_payer_is_refused():
    import x402_payments
    from types import SimpleNamespace

    assert not x402_payments._allow_wallet_payment(SimpleNamespace(payload={}), now=1000)


def test_approved_price_bands_are_exact_and_valid():
    import x402_payments

    x402_payments.validate_price_bands()
    assert x402_payments.PRICE_BANDS_ATOMIC == {
        "lookup": 2_000,
        "signal": 5_000,
        "evidence": 10_000,
        "feed_batch": 20_000,
        "heavy": 50_000,
    }
    assert x402_payments.TOOL_PRICE_BANDS == {
        "kreditvakt_score_company_v1": "lookup",
        "swedish_company_verify_v1": "lookup",
        "swedish_company_changes_v1": "feed_batch",
        "danish_company_verify_v1": "lookup",
        "danish_company_changes_v1": "feed_batch",
        "norwegian_company_verify_v1": "lookup",
        "norwegian_company_changes_v1": "feed_batch",
        "finnish_company_verify_v1": "lookup",
        "finnish_company_changes_v1": "feed_batch",
        "estonian_company_verify_v1": "lookup",
        "estonian_company_changes_v1": "feed_batch",
        "french_company_verify_v1": "lookup",
        "french_company_changes_v1": "feed_batch",
    }


def test_invalid_price_band_is_rejected(monkeypatch):
    import x402_payments

    monkeypatch.setattr(x402_payments, "PRICE_BANDS_ATOMIC", {
        "lookup": 5_000,
        "signal": 2_000,
        "evidence": 10_000,
        "feed_batch": 20_000,
        "heavy": 50_000,
    })
    with pytest.raises(X402ConfigurationError, match="increasing"):
        x402_payments.validate_price_bands()
