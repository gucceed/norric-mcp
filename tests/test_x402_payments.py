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
        "X402_DATA_FRESHNESS_PRICE": "$0.01",
    })
    assert config == {
        "network": BASE_SEPOLIA,
        "pay_to": "0x" + "1" * 40,
        "facilitator_url": "https://facilitator.eu.example",
        "price": "$0.01",
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

    sentinel = object()

    def fake_wrapper(server, *, accepts, resource):
        captured["accepts"] = accepts
        captured["resource"] = resource
        return lambda handler: sentinel

    monkeypatch.setattr("x402.http.HTTPFacilitatorClient", FakeFacilitator)
    monkeypatch.setattr("x402.x402ResourceServer", FakeServer)
    monkeypatch.setattr("x402.mcp.create_payment_wrapper", fake_wrapper)

    wrapper = x402_payments.build_data_freshness_wrapper({
        "X402_TESTNET_ENABLED": "true",
        "X402_NETWORK": BASE_SEPOLIA,
        "X402_PAY_TO": "0x" + "1" * 40,
        "X402_FACILITATOR_URL": "https://facilitator.eu.example",
        "X402_DATA_FRESHNESS_PRICE": "$0.01",
    })
    assert wrapper(lambda: None) is sentinel
    assert captured["facilitator"] == {"url": "https://facilitator.eu.example"}
    assert captured["registered"] == BASE_SEPOLIA
    assert captured["initialized"] is True
    assert captured["resource_config"].network == BASE_SEPOLIA
    assert captured["resource_config"].pay_to == "0x" + "1" * 40
    assert captured["resource_config"].price == "$0.01"
    assert captured["resource_config"].max_timeout_seconds == 120
    assert captured["accepts"] == ["requirement"]
