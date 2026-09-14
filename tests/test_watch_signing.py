"""
tests/test_watch_signing.py

100% coverage on watch/signing.py — the customer-facing HMAC contract.
Run with: pytest tests/test_watch_signing.py -v --tb=short
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watch.signing import (
    DEFAULT_TOLERANCE_SECONDS,
    sign_body,
    signature_header,
    verify_signature_header,
)

SECRET = "whsec_" + "ab" * 24
BODY = b'{"id":"evt_1","type":"company.risk_tier_changed"}'


class TestSignBody:
    def test_deterministic(self):
        assert sign_body(SECRET, 1726410000, BODY) == sign_body(SECRET, 1726410000, BODY)

    def test_hex_sha256_length(self):
        assert len(sign_body(SECRET, 1726410000, BODY)) == 64

    def test_timestamp_is_signed(self):
        assert sign_body(SECRET, 1726410000, BODY) != sign_body(SECRET, 1726410001, BODY)

    def test_secret_changes_signature(self):
        assert sign_body(SECRET, 1, BODY) != sign_body("whsec_other", 1, BODY)


class TestSignatureHeader:
    def test_format(self):
        h = signature_header(SECRET, BODY, timestamp=1726410000)
        assert h.startswith("t=1726410000,v1=")
        assert len(h.split("v1=")[1]) == 64

    def test_roundtrip_verifies(self):
        h = signature_header(SECRET, BODY, timestamp=1726410000)
        assert verify_signature_header(SECRET, h, BODY, now=1726410000)

    def test_tampered_body_fails(self):
        h = signature_header(SECRET, BODY, timestamp=1726410000)
        assert not verify_signature_header(SECRET, h, BODY + b" ", now=1726410000)

    def test_wrong_secret_fails(self):
        h = signature_header(SECRET, BODY, timestamp=1726410000)
        assert not verify_signature_header("whsec_other", h, BODY, now=1726410000)


class TestVerifyEdgeCases:
    def _h(self, ts=1726410000):
        return signature_header(SECRET, BODY, timestamp=ts)

    def test_within_tolerance_ok(self):
        h = self._h()
        assert verify_signature_header(SECRET, h, BODY, now=1726410000 + DEFAULT_TOLERANCE_SECONDS)

    def test_stale_timestamp_rejected(self):
        h = self._h()
        assert not verify_signature_header(
            SECRET, h, BODY, now=1726410000 + DEFAULT_TOLERANCE_SECONDS + 1
        )

    def test_future_timestamp_rejected(self):
        h = self._h()
        assert not verify_signature_header(
            SECRET, h, BODY, now=1726410000 - DEFAULT_TOLERANCE_SECONDS - 1
        )

    def test_malformed_headers_rejected(self):
        for bad in ["", "t=abc,v1=00", "v1=00", "garbage", "t=1"]:
            assert not verify_signature_header(SECRET, bad, BODY, now=1726410000)

    def test_zero_tolerance_accepted_when_now_none(self):
        # now=None path: uses wall clock, must verify its own fresh header
        h = signature_header(SECRET, BODY)
        assert verify_signature_header(SECRET, h, BODY)
