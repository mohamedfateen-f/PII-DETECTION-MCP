

from pii_anonymizer import (
    PII_PATTERNS,
    anonymize_data,
    anonymize_text,
    contains_pii,
    detect_pii,
    mask_value,
)


class TestPatterns:
    def test_six_pii_patterns_are_registered(self):
        assert set(PII_PATTERNS) == {
            "EMAIL",
            "PHONE",
            "PAN",
            "AADHAAR",
            "CREDIT_CARD",
            "IP_ADDRESS",
        }

    def test_detection_is_based_on_patterns_not_column_names(self):
        matches = detect_pii("reach me on 9876543210")

        assert [match["type"] for match in matches] == ["PHONE"]
        assert matches[0]["value"] == "9876543210"

    def test_contains_pii_ignores_non_pii_values(self):
        assert contains_pii("john@example.com")
        assert contains_pii(9876543210)
        assert not contains_pii("Chennai")
        assert not contains_pii(None)
        assert not contains_pii(1001)

    def test_email_pattern_matches(self):
        assert PII_PATTERNS["EMAIL"].search("mail me at john.doe@example.com now")

    def test_phone_pattern_matches_indian_numbers(self):
        for value in ("9876543210", "+91 9876543210", "+91-9876543210"):
            assert PII_PATTERNS["PHONE"].search(value), value

    def test_phone_pattern_misses_country_code_without_separator(self):
        assert PII_PATTERNS["PHONE"].search("+919876543210") is None

    def test_pan_pattern_requires_uppercase_shape(self):
        assert PII_PATTERNS["PAN"].search("ABCDE1234F")
        assert not PII_PATTERNS["PAN"].search("abcde1234f")

    def test_aadhaar_pattern_requires_separators(self):
        assert PII_PATTERNS["AADHAAR"].search("1234-5678-9012")
        assert PII_PATTERNS["AADHAAR"].search("1234 5678 9012")
        assert not PII_PATTERNS["AADHAAR"].search("123456789012")

    def test_credit_card_pattern_matches_spaced_and_hyphenated(self):
        assert PII_PATTERNS["CREDIT_CARD"].search("1234-5678-9012-3456")
        assert PII_PATTERNS["CREDIT_CARD"].search("1234 5678 9012 3456")

    def test_ip_pattern_matches_ipv4_shape(self):
        assert PII_PATTERNS["IP_ADDRESS"].search("192.168.1.100")


class TestMaskValue:
    def test_email_masks_username_keeps_domain(self):
        assert mask_value("EMAIL", "john@example.com") == "j***@example.com"

    def test_email_with_short_username_is_fully_masked(self):
        assert mask_value("EMAIL", "ab@x.com") == "**@x.com"

    def test_phone_keeps_last_four_digits(self):
        assert mask_value("PHONE", "9876543210") == "******3210"

    def test_phone_with_country_code_keeps_last_four_digits(self):
        assert mask_value("PHONE", "+91 9876543210") == "********3210"

    def test_pan_keeps_last_four_characters(self):
        assert mask_value("PAN", "ABCDE1234F") == "*****234F"

    def test_aadhaar_keeps_last_four_digits(self):
        assert mask_value("AADHAAR", "1234-5678-9012") == "XXXX XXXX 9012"
        assert mask_value("AADHAAR", "1234 5678 9012") == "XXXX XXXX 9012"

    def test_credit_card_keeps_last_four_digits(self):
        assert (
            mask_value("CREDIT_CARD", "1234-5678-9012-3456")
            == "**** **** **** 3456"
        )
        assert (
            mask_value("CREDIT_CARD", "1234 5678 9012 3456")
            == "**** **** **** 3456"
        )

    def test_ip_address_masks_last_two_octets(self):
        assert mask_value("IP_ADDRESS", "192.168.1.100") == "192.168.XXX.XXX"

    def test_unknown_pii_type_is_masked_with_asterisks(self):
        assert mask_value("BOGUS", "abcdef") == "******"


class TestAnonymizeText:
    def test_masks_multiple_values_in_one_string(self):
        assert (
            anonymize_text("Contact john@example.com or 9876543210")
            == "Contact j***@example.com or ******3210"
        )

    def test_masks_mixed_pii_types_right_to_left(self):
        assert (
            anonymize_text("id 1234-5678-9012 and card 1111-2222-3333-4444")
            == "id XXXX XXXX 9012 and card **** **** **** 4444"
        )

    def test_none_is_returned_unchanged(self):
        assert anonymize_text(None) is None

    def test_non_string_values_are_stringified(self):
        assert anonymize_text(123) == "123"

    def test_text_without_pii_is_returned_unchanged(self):
        assert anonymize_text("Chennai") == "Chennai"

    def test_country_code_prefix_survives_masking(self):
        assert anonymize_text("+91 9876543210") == "+91 ******3210"

    def test_lowercase_pan_is_left_unchanged(self):
        assert anonymize_text("abcde1234f") == "abcde1234f"

    def test_unseparated_aadhaar_is_left_unchanged(self):
        assert anonymize_text("123456789012") == "123456789012"

    def test_ip_octets_are_not_validated(self):
        assert (
            anonymize_text("999.999.999.999") == "999.999.XXX.XXX"
        )


class TestAnonymizeData:
    def test_pii_values_are_masked_and_other_values_kept(self):
        data = {
            "Customer_ID": 1001,
            "Name": "Mohamed Fateen",
            "Email": "mohamed@gmail.com",
            "Phone": "9876543210",
            "PAN": "ABCDE1234F",
            "Aadhaar": "1234 5678 9012",
            "City": "Chennai",
        }

        assert anonymize_data(data) == {
            "Customer_ID": 1001,
            "Name": "Mohamed Fateen",
            "Email": "m******@gmail.com",
            "Phone": "******3210",
            "PAN": "*****234F",
            "Aadhaar": "XXXX XXXX 9012",
            "City": "Chennai",
        }

    def test_unlisted_column_names_are_masked(self):
        data = {
            "contact_detail_1": "a@b.com",
            "reach_me_at": "9876543210",
            "last_seen_from": "10.0.0.1",
        }

        assert anonymize_data(data) == {
            "contact_detail_1": "*@b.com",
            "reach_me_at": "******3210",
            "last_seen_from": "10.0.XXX.XXX",
        }

    def test_values_without_pii_are_returned_unchanged(self):
        data = {"customer_id": 1, "notes": "call later", "city": "Chennai"}

        assert anonymize_data(data) == data

    def test_pii_inside_free_text_of_any_column_is_masked(self):
        data = {"notes": "mail me at john@example.com"}

        assert anonymize_data(data) == {
            "notes": "mail me at j***@example.com"
        }

    def test_none_values_are_preserved(self):
        assert anonymize_data({"email": None}) == {"email": None}

    def test_original_dict_is_not_mutated(self):
        data = {"name": "John", "email": "john@example.com"}

        anonymize_data(data)

        assert data == {"name": "John", "email": "john@example.com"}

    def test_input_keys_are_preserved_in_order(self):
        data = {"name": "John", "email": "john@example.com", "city": "Chennai"}

        assert list(anonymize_data(data)) == ["name", "email", "city"]
