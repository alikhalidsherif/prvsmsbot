from __future__ import annotations

import unittest

from bot.categories import (
    MessageCategoryRules,
    classify_origin,
    is_personal_sender,
    is_service_sender,
    normalize_sender,
)

# ---------------------------------------------------------------------------
# Shared rules instance (default sub-classification patterns)
# ---------------------------------------------------------------------------

RULES = MessageCategoryRules()


# ---------------------------------------------------------------------------
# normalize_sender
# ---------------------------------------------------------------------------


class TestNormalizeSender(unittest.TestCase):
    def test_bare_251_gets_plus_prefix(self) -> None:
        self.assertEqual(normalize_sender("251911223344"), "+251911223344")

    def test_already_plus_251_unchanged(self) -> None:
        self.assertEqual(normalize_sender("+251911223344"), "+251911223344")

    def test_named_sender_unchanged(self) -> None:
        self.assertEqual(normalize_sender("CBE"), "CBE")

    def test_short_code_unchanged(self) -> None:
        self.assertEqual(normalize_sender("127"), "127")

    def test_strips_whitespace(self) -> None:
        self.assertEqual(normalize_sender("  +251911223344  "), "+251911223344")

    def test_none_becomes_empty_string(self) -> None:
        self.assertEqual(normalize_sender(None), "")

    def test_empty_string_stays_empty(self) -> None:
        self.assertEqual(normalize_sender(""), "")


# ---------------------------------------------------------------------------
# is_service_sender
# ---------------------------------------------------------------------------


class TestIsServiceSender(unittest.TestCase):
    # Named senders (contain letters)
    def test_named_alpha_only(self) -> None:
        self.assertTrue(is_service_sender("CBE"))

    def test_named_mixed_case(self) -> None:
        self.assertTrue(is_service_sender("Telebirr"))

    def test_named_lowercase(self) -> None:
        self.assertTrue(is_service_sender("awash"))

    def test_named_alphanumeric(self) -> None:
        self.assertTrue(is_service_sender("BOA2u"))

    def test_named_with_spaces(self) -> None:
        self.assertTrue(is_service_sender("Commercial Bank"))

    # Short numeric codes (≤ 6 digits)
    def test_short_code_3_digits(self) -> None:
        self.assertTrue(is_service_sender("127"))

    def test_short_code_4_digits(self) -> None:
        self.assertTrue(is_service_sender("9946"))

    def test_short_code_6_digits(self) -> None:
        self.assertTrue(is_service_sender("123456"))

    # NOT service — full ET numbers
    def test_full_et_number_not_service(self) -> None:
        self.assertFalse(is_service_sender("+251911223344"))

    def test_full_et_number_12_digits_not_service(self) -> None:
        self.assertFalse(is_service_sender("+251972345678"))

    # NOT service — 7-digit or longer pure-digit strings that aren't ET numbers
    def test_long_digit_string_not_service(self) -> None:
        self.assertFalse(is_service_sender("1234567"))


# ---------------------------------------------------------------------------
# is_personal_sender
# ---------------------------------------------------------------------------


class TestIsPersonalSender(unittest.TestCase):
    def test_normalised_et_number(self) -> None:
        self.assertTrue(is_personal_sender("+251911223344"))

    def test_another_valid_et_number(self) -> None:
        self.assertTrue(is_personal_sender("+251972345678"))

    # Must have + prefix after normalisation
    def test_bare_251_without_plus_is_not_personal(self) -> None:
        # normalize_sender should be called first; raw "251..." without "+" fails
        self.assertFalse(is_personal_sender("251911223344"))

    def test_named_sender_not_personal(self) -> None:
        self.assertFalse(is_personal_sender("CBE"))

    def test_short_code_not_personal(self) -> None:
        self.assertFalse(is_personal_sender("127"))

    def test_too_short_et_prefix_not_personal(self) -> None:
        # Only 8 subscriber digits instead of 9
        self.assertFalse(is_personal_sender("+25191122334"))

    def test_too_long_et_number_not_personal(self) -> None:
        # 10 subscriber digits instead of 9
        self.assertFalse(is_personal_sender("+2519112233440"))

    def test_different_country_code_not_personal(self) -> None:
        self.assertFalse(is_personal_sender("+441234567890"))

    def test_empty_string_not_personal(self) -> None:
        self.assertFalse(is_personal_sender(""))


# ---------------------------------------------------------------------------
# classify_origin — kind
# ---------------------------------------------------------------------------


class TestClassifyOriginKind(unittest.TestCase):
    def test_named_sender_is_service(self) -> None:
        result = classify_origin("CBE", "your balance is 500 ETB", RULES)
        self.assertEqual(result["kind"], "service")

    def test_short_code_is_service(self) -> None:
        result = classify_origin("127", "data bundle activated", RULES)
        self.assertEqual(result["kind"], "service")

    def test_et_number_bare_is_personal(self) -> None:
        # bare 251... gets normalised to +251...
        result = classify_origin("251911223344", "hey how are you", RULES)
        self.assertEqual(result["kind"], "personal")

    def test_et_number_plus_is_personal(self) -> None:
        result = classify_origin("+251911223344", "hello", RULES)
        self.assertEqual(result["kind"], "personal")

    def test_none_sender_is_unknown(self) -> None:
        result = classify_origin(None, "some content", RULES)
        self.assertEqual(result["kind"], "unknown")

    def test_empty_sender_is_unknown(self) -> None:
        result = classify_origin("", "some content", RULES)
        self.assertEqual(result["kind"], "unknown")

    def test_international_number_is_unknown(self) -> None:
        result = classify_origin("+12025551234", "hello from the US", RULES)
        self.assertEqual(result["kind"], "unknown")

    def test_malformed_sender_is_unknown(self) -> None:
        result = classify_origin("??%%##", "garbage", RULES)
        self.assertEqual(result["kind"], "unknown")


# ---------------------------------------------------------------------------
# classify_origin — service sub-classification
# ---------------------------------------------------------------------------


class TestServiceSubclassification(unittest.TestCase):
    def _classify(self, sender: str, content: str) -> dict[str, str]:
        return classify_origin(sender, content, RULES)

    # bank
    def test_cbe_keyword_in_sender(self) -> None:
        r = self._classify("CBE", "your account balance has changed")
        self.assertEqual(r["origin"], "bank")
        self.assertEqual(r["label"], "service:bank")

    def test_bank_keyword_in_content(self) -> None:
        r = self._classify("Alerts", "Awash bank transaction completed")
        self.assertEqual(r["origin"], "bank")

    def test_telebirr_in_sender_is_bank(self) -> None:
        r = self._classify("telebirr", "payment received")
        self.assertEqual(r["origin"], "bank")

    def test_dashen_in_content_is_bank(self) -> None:
        r = self._classify("BankService", "Dashen transfer of 200 ETB")
        self.assertEqual(r["origin"], "bank")

    # telecom
    def test_ethio_in_content_is_telecom(self) -> None:
        r = self._classify("127", "Ethio telecom data package expired")
        self.assertEqual(r["origin"], "telecom")

    def test_994_short_code_content_telecom(self) -> None:
        r = self._classify("994", "your package has been activated")
        # 994 matches telecom_patterns in the sender portion of the text blob
        self.assertEqual(r["origin"], "telecom")

    def test_telecom_keyword_in_content(self) -> None:
        r = self._classify("EthioTel", "telecom balance updated")
        self.assertEqual(r["origin"], "telecom")

    # otp
    def test_otp_keyword_in_content(self) -> None:
        r = self._classify("MyApp", "Your OTP is 483920")
        self.assertEqual(r["origin"], "otp")

    def test_verification_keyword(self) -> None:
        r = self._classify("ServiceX", "Use this verification code: 991234")
        self.assertEqual(r["origin"], "otp")

    def test_pin_keyword(self) -> None:
        r = self._classify("Notify", "Your PIN is 7734")
        self.assertEqual(r["origin"], "otp")

    # generic service (no keyword match)
    def test_unknown_service_sender_no_keyword(self) -> None:
        r = self._classify("ACME", "Your order has been shipped")
        self.assertEqual(r["origin"], "service")
        self.assertEqual(r["label"], "service:service")

    def test_short_code_no_keyword(self) -> None:
        r = self._classify("55500", "Promo offer available now")
        self.assertEqual(r["origin"], "service")


# ---------------------------------------------------------------------------
# classify_origin — label field
# ---------------------------------------------------------------------------


class TestClassifyOriginLabel(unittest.TestCase):
    def test_personal_label(self) -> None:
        r = classify_origin("+251912345678", "hi", RULES)
        self.assertEqual(r["label"], "personal")

    def test_unknown_label(self) -> None:
        r = classify_origin(None, "hi", RULES)
        self.assertEqual(r["label"], "unknown")

    def test_service_bank_label(self) -> None:
        r = classify_origin("CBE", "balance alert", RULES)
        self.assertEqual(r["label"], "service:bank")

    def test_service_otp_label(self) -> None:
        r = classify_origin("Auth", "your code is 1234", RULES)
        self.assertEqual(r["label"], "service:otp")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    def test_none_content_does_not_crash(self) -> None:
        r = classify_origin("CBE", None, RULES)
        self.assertEqual(r["kind"], "service")

    def test_both_none_is_unknown(self) -> None:
        r = classify_origin(None, None, RULES)
        self.assertEqual(r["kind"], "unknown")

    def test_content_alone_cannot_make_personal(self) -> None:
        # Personal routing is sender-driven, not content-driven
        r = classify_origin("CBE", "+251911223344 sent you money", RULES)
        self.assertEqual(r["kind"], "service")

    def test_251_prefix_without_enough_digits_is_not_personal(self) -> None:
        # "251" alone normalises to "+251" which doesn't match the ET regex
        r = classify_origin("251", "hi", RULES)
        # +251 has letters? No. Short code? digits = "251", len = 3 → service
        self.assertEqual(r["kind"], "service")

    def test_et_number_with_bank_content_is_personal_not_service(self) -> None:
        # Personal sender wins regardless of content keywords
        r = classify_origin("+251911223344", "CBE bank balance 1000 ETB", RULES)
        self.assertEqual(r["kind"], "personal")


if __name__ == "__main__":
    unittest.main()
