"""
Tests for agent/classifier.py's deterministic gibberish gate.
"""
from agent.classifier import gibberish_rejection_reason


class TestGibberishRejectionReason:
    def test_empty_string_rejected(self):
        assert gibberish_rejection_reason("") is not None

    def test_whitespace_only_rejected(self):
        assert gibberish_rejection_reason("   \n\t  ") is not None

    def test_keyboard_mash_rejected(self):
        assert gibberish_rejection_reason("asdkfjhskdjfh sldkjf qwpoeiru") is not None

    def test_single_gibberish_token_rejected(self):
        assert gibberish_rejection_reason("asdkfjhskdjfh") is not None

    def test_digits_and_symbols_only_rejected(self):
        assert gibberish_rejection_reason("!!! 12345 ### ???") is not None

    def test_real_anomaly_description_accepted(self):
        assert gibberish_rejection_reason("Sales dropped sharply at store S036 last week") is None

    def test_vague_but_real_report_accepted(self):
        assert gibberish_rejection_reason("something's wrong with returns lately") is None

    def test_entity_id_heavy_description_accepted(self):
        assert gibberish_rejection_reason("Stockout for SKU P0108 at store S036, supplier SUP07 delayed") is None

    def test_short_real_query_accepted(self):
        assert gibberish_rejection_reason("returns are up") is None
