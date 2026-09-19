from pathlib import Path

SOURCE = Path("x402_facilitator/app.py").read_text()

def test_facilitator_is_sepolia_only():
    assert 'NETWORK = "eip155:84532"' in SOURCE
    assert '!= NETWORK' in SOURCE
    assert 'NETWORK = "eip155:8453"' not in SOURCE

def test_no_private_key_literal_or_logging():
    assert 'os.environ["EVM_PRIVATE_KEY"]' in SOURCE
    assert "print(private_key)" not in SOURCE
    assert "logger" not in SOURCE

def test_health_declares_testnet():
    assert '"mode": "testnet"' in SOURCE
