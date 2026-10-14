import re


PII_PATTERNS = {

    "EMAIL": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    ),

    "PHONE": re.compile(
        r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b"
    ),

    "PAN": re.compile(
        r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"
    ),

    "AADHAAR": re.compile(
        r"\b\d{4}[-\s]\d{4}[-\s]\d{4}\b"
    ),

    "CREDIT_CARD": re.compile(
        r"\b(?:\d{4}[-\s]?){3}\d{4}\b"
    ),

    "IP_ADDRESS": re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ),
}


def mask_value(pii_type: str, value: str) -> str:

    if pii_type == "EMAIL":

        username, domain = value.split("@", 1)

        if len(username) <= 2:
            masked_username = "*" * len(username)
        else:
            masked_username = (
                username[0]
                + "*" * (len(username) - 1)
            )

        return f"{masked_username}@{domain}"

    if pii_type == "PHONE":

        digits = "".join(
            char for char in value
            if char.isdigit()
        )

        return "*" * (len(digits) - 4) + digits[-4:]

    if pii_type == "PAN":

        return "*****" + value[-4:]

    if pii_type == "AADHAAR":

        digits = "".join(
            char for char in value
            if char.isdigit()
        )

        return f"XXXX XXXX {digits[-4:]}"

    if pii_type == "CREDIT_CARD":

        digits = "".join(
            char for char in value
            if char.isdigit()
        )

        return "**** **** **** " + digits[-4:]

    if pii_type == "IP_ADDRESS":

        parts = value.split(".")

        return f"{parts[0]}.{parts[1]}.XXX.XXX"

    return "*" * len(value)


def detect_pii(value) -> list[dict]:

    if value is None:
        return []

    text = value if isinstance(value, str) else str(value)

    matches = []

    for pii_type, pattern in PII_PATTERNS.items():

        for match in pattern.finditer(text):

            matches.append({
                "type": pii_type,
                "start": match.start(),
                "end": match.end(),
                "value": match.group()
            })

    matches.sort(
        key=lambda item: item["start"],
        reverse=True
    )

    return matches


def contains_pii(value) -> bool:

    return bool(detect_pii(value))


def anonymize_text(text: str) -> str:

    if text is None:
        return text

    text = str(text)

    for match in detect_pii(text):

        replacement = mask_value(
            match["type"],
            match["value"]
        )

        text = (
            text[:match["start"]]
            + replacement
            + text[match["end"]:]
        )

    return text


def anonymize_data(data: dict) -> dict:

    anonymized = {}

    for column, value in data.items():

        if contains_pii(value):

            anonymized[column] = anonymize_text(value)

        else:

            anonymized[column] = value

    return anonymized
