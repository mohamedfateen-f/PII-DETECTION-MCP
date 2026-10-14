# PostgreSQL Connection and PII Anonymization

## 1. Overview

This module provides two core capabilities:

1. **PostgreSQL database connectivity** using `psycopg`.
2. **PII detection and anonymization** using regular expressions.

The database connection utility reads PostgreSQL credentials from environment variables and provides a reusable connection function.

The PII anonymization component detects sensitive information such as email addresses, phone numbers, PAN numbers, Aadhaar numbers, credit-card numbers, and IP addresses. Detected values are masked before being stored or processed.

A key design principle is that **sensitivity is detected from the value itself using the PII patterns**, never from a hard-coded list of column names. Values that match no pattern, such as `name` and `city`, remain unchanged.

---

# 2. PostgreSQL Database Connection

## 2.1 Required Libraries

```python
import os

import psycopg
from dotenv import load_dotenv
```

### `os`

The `os` module is used to retrieve database configuration from environment variables.

### `psycopg`

`psycopg` is the PostgreSQL database driver used to establish database connections.

### `python-dotenv`

`load_dotenv()` loads configuration values from a `.env` file into the application's environment.

---

## 2.2 Loading Environment Variables

```python
load_dotenv()

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")
```

The application reads the following configuration values:

| Variable      | Description                | Default     |
| ------------- | -------------------------- | ----------- |
| `PG_HOST`     | PostgreSQL server hostname | `localhost` |
| `PG_PORT`     | PostgreSQL server port     | `5432`      |
| `PG_USER`     | PostgreSQL username        | None        |
| `PG_PASSWORD` | PostgreSQL password        | None        |

Example `.env` configuration:

```env
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=your_password
```

Keeping credentials in environment variables prevents database credentials from being hard-coded directly into the application source code.

---

# 3. Database Connection Function

```python
def get_connection(database: str = "postgres"):
    return psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=database,
    )
```

The `get_connection()` function creates a connection to the requested PostgreSQL database.

### Parameters

| Parameter  | Type       | Description                                 |
| ---------- | ---------- | ------------------------------------------- |
| `database` | `str`      | PostgreSQL database name                    |
| Default    | `postgres` | Connects to the default PostgreSQL database |

Example:

```python
conn = get_connection("my_database")
```

The function can therefore be reused by different database operations without duplicating connection configuration.

---

# 4. PII Detection

The PII component uses Python's `re` module.

```python
import re
```

Regular expressions are used to identify patterns corresponding to different types of personally identifiable information.

The supported PII types are:

* Email
* Phone number
* PAN
* Aadhaar
* Credit card
* IP address

---

# 5. PII Patterns

The patterns are stored in the `PII_PATTERNS` dictionary.

```python
PII_PATTERNS = {
    ...
}
```

Each entry associates a PII type with a compiled regular expression.

## 5.1 Email

```python
"EMAIL": re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
```

Detects common email addresses.

Example:

```text
john@example.com
```

The domain is preserved while the username is partially masked.

Result:

```text
j***@example.com
```

---

## 5.2 Phone Number

```python
"PHONE": re.compile(
    r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b"
)
```

Detects Indian phone numbers with or without the `+91` country code.

Examples:

```text
9876543210
+919876543210
+91 9876543210
```

The masking function preserves the last four digits.

Example:

```text
******3210
```

---

## 5.3 PAN

```python
"PAN": re.compile(
    r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"
)
```

Detects PAN-style values.

Example:

```text
ABCDE1234F
```

Result:

```text
*****1234F
```

---

## 5.4 Aadhaar

```python
"AADHAAR": re.compile(
    r"\b\d{4}[-\s]\d{4}[-\s]\d{4}\b"
)
```

Detects Aadhaar values containing separators.

Examples:

```text
1234-5678-9012
1234 5678 9012
```

Result:

```text
XXXX XXXX 9012
```

---

## 5.5 Credit Card

```python
"CREDIT_CARD": re.compile(
    r"\b(?:\d{4}[-\s]?){3}\d{4}\b"
)
```

Detects 16-digit credit-card-style values, including values containing spaces or hyphens.

Example:

```text
1234-5678-9012-3456
```

Result:

```text
**** **** **** 3456
```

---

## 5.6 IP Address

```python
"IP_ADDRESS": re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)
```

Detects IPv4-style addresses.

Example:

```text
192.168.1.100
```

Result:

```text
192.168.XXX.XXX
```

> The current regular expression identifies IPv4-shaped values but does not validate whether every octet is within the `0-255` range.

---

# 6. PII Masking

The `mask_value()` function determines how each detected PII type should be anonymized.

```python
def mask_value(pii_type: str, value: str) -> str:
```

The function receives:

* `pii_type` — the detected PII category.
* `value` — the original sensitive value.

Different PII types use different masking strategies.

---

# 7. Email Masking

For email addresses, the username is partially masked while the domain remains visible.

```python
username, domain = value.split("@", 1)
```

For usernames longer than two characters:

```text
john@example.com
```

becomes:

```text
j***@example.com
```

For very short usernames, all username characters are replaced with `*`.

---

# 8. Phone Masking

The implementation first removes formatting characters:

```python
digits = "".join(
    char for char in value
    if char.isdigit()
)
```

Only the final four digits are retained.

Example:

```text
+91 9876543210
```

becomes:

```text
******3210
```

---

# 9. PAN Masking

The first five characters are replaced with asterisks while the final four characters are retained.

Example:

```text
ABCDE1234F
```

becomes:

```text
*****234F
```

The implementation is:

```python
return "*****" + value[-4:]
```

---

# 10. Aadhaar Masking

The function removes spaces and hyphens and retains only the final four digits.

Example:

```text
1234-5678-9012
```

becomes:

```text
XXXX XXXX 9012
```

---

# 11. Credit Card Masking

The separators are removed and only the final four digits are preserved.

Example:

```text
1234-5678-9012-3456
```

becomes:

```text
**** **** **** 3456
```

---

# 12. IP Address Masking

The IP address is split into its four components.

```python
parts = value.split(".")
```

The first two components are preserved while the last two are replaced.

Example:

```text
192.168.1.100
```

becomes:

```text
192.168.XXX.XXX
```

---

# 13. Text Anonymization

The `anonymize_text()` function detects and replaces PII inside arbitrary text.

```python
def anonymize_text(text: str) -> str:
```

This allows a value containing multiple types of PII to be processed.

For example:

```text
Contact john@example.com or 9876543210
```

can become:

```text
j***@example.com or ******3210
```

---

## 13.1 Handling Null Values

```python
if text is None:
    return text
```

`None` values are returned unchanged.

---

## 13.2 Detecting Matches

The matching itself lives in `detect_pii()`, which iterates through every configured PII pattern:

```python
for pii_type, pattern in PII_PATTERNS.items():

    for match in pattern.finditer(text):
```

Each detected match stores:

```python
{
    "type": pii_type,
    "start": match.start(),
    "end": match.end(),
    "value": match.group()
}
```

This records:

* PII type
* Starting position
* Ending position
* Original matched value

---

# 14. Right-to-Left Replacement

`detect_pii()` sorts the detected matches in reverse order:

```python
matches.sort(
    key=lambda item: item["start"],
    reverse=True
)
```

`anonymize_text()` then walks that list, so the replacements are performed from the end of the string toward the beginning.

This is important because replacing text changes the string length.

For example, if multiple PII values exist in one string, replacing the first value could change the indexes of later values.

Replacing from right to left prevents previously calculated positions from becoming invalid.

---

# 15. Pattern-Based PII Detection

The module does not maintain a list of column names.

Instead, every value is scanned with the regular expressions defined in `PII_PATTERNS`:

```python
def detect_pii(value) -> list[dict]:
```

`detect_pii()` returns one entry per match:

```python
{
    "type": "EMAIL",
    "start": 9,
    "end": 25,
    "value": "john@ex.io"
}
```

If the returned list is empty, the value contains no recognizable PII.

`contains_pii()` is a thin helper used by `anonymize_data()`:

```python
def contains_pii(value) -> bool:

    return bool(detect_pii(value))
```

Because detection is value-based, a column named `notes` holding an email address is masked just like a column named `email`, and a newly added column requires no registration.

---

# 16. Data-Level Anonymization

The `anonymize_data()` function processes an entire dictionary representing a database record.

```python
def anonymize_data(data: dict) -> dict:
```

For every column, the value is tested against the PII patterns:

```python
if contains_pii(value):
```

If PII is detected:

```python
anonymized[column] = anonymize_text(value)
```

Otherwise:

```python
anonymized[column] = value
```

Therefore, values that match no pattern are preserved unchanged and keep their original type.

Example input:

```python
{
    "name": "John",
    "email": "john@example.com",
    "phone": "9876543210",
    "city": "Chennai"
}
```

Result:

```python
{
    "name": "John",
    "email": "j***@example.com",
    "phone": "******3210",
    "city": "Chennai"
}
```

The `name` field is **not anonymized** because the value `"John"` matches no PII pattern.

---

# 17. Processing Flow

The overall anonymization flow is:

```text
Input Data
    |
    v
Check each value
    |
    v
Does the value match a PII pattern?
   / \
 Yes  No
  |    |
  v    v
Apply masking   Keep value unchanged
  |
  v
Return anonymized data
```

For a database record:

```text
Incoming Record
       |
       v
 anonymize_data()
       |
       +---- name ---------> unchanged
       |
       +---- city ---------> unchanged
       |
       +---- email --------> anonymized
       |
       +---- phone --------> anonymized
       |
       +---- PAN ----------> anonymized
       |
       +---- Aadhaar ------> anonymized
       |
       +---- credit_card --> anonymized
       |
       +---- IP address ---> anonymized
       |
       v
Anonymized Record
```

---

# 18. Security Design

The module follows a value-based anonymization approach.

Instead of anonymizing every string value indiscriminately, it first checks whether the value actually matches one of the `PII_PATTERNS` regular expressions.

This prevents fields such as:

```text
name
city
country
address
department
```

from being unintentionally modified merely because they contain text.

For example:

```python
{
    "name": "John",
    "email": "john@example.com",
    "city": "Chennai"
}
```

produces:

```python
{
    "name": "John",
    "email": "j***@example.com",
    "city": "Chennai"
}
```

The same record with an unrecognised column name is handled identically:

```python
{
    "contact_detail_1": "john@example.com"
}
```

produces:

```python
{
    "contact_detail_1": "j***@example.com"
}
```

---

# 19. Configuration and Extensibility

Additional PII types can be added to `PII_PATTERNS`.

For example, a new PII type can be introduced by adding:

```python
"NEW_TYPE": re.compile(r"...")
```

A corresponding masking rule can then be added to `mask_value()`.

No other change is needed. Detection, record-level processing, and any database column that happens to hold such a value are covered automatically.

This separates:

1. **PII detection** (`PII_PATTERNS`, `detect_pii()`)
2. **PII masking** (`mask_value()`, `anonymize_text()`)

and makes the implementation easier to extend.

---

# 20. Dependencies

The module requires:

```text
psycopg
python-dotenv
```

Python's following modules are built in:

```text
os
re
```

Example installation:

```powershell
pip install psycopg[binary] python-dotenv
```

---

# 21. Example

### Input

```python
data = {
    "name": "John",
    "email": "john.doe@example.com",
    "phone": "+91 9876543210",
    "pan": "ABCDE1234F",
    "aadhaar": "1234-5678-9012",
    "credit_card": "1234-5678-9012-3456",
    "ip_address": "192.168.1.100",
    "city": "Chennai"
}
```

### Processing

```python
result = anonymize_data(data)
```

### Output

```python
{
    "name": "John",
    "email": "j*******@example.com",
    "phone": "******3210",
    "pan": "*****234F",
    "aadhaar": "XXXX XXXX 9012",
    "credit_card": "**** **** **** 3456",
    "ip_address": "192.168.XXX.XXX",
    "city": "Chennai"
}
```

The sensitive information is masked while values that match no PII pattern remain unchanged.

---

# 22. Summary

This module provides a reusable foundation for protecting PII before data is processed or stored.

### Main components

| Component          | Responsibility                                        |
| ------------------ | ----------------------------------------------------- |
| `load_dotenv()`    | Load environment configuration                        |
| `get_connection()` | Create PostgreSQL connections                         |
| `PII_PATTERNS`     | Define detectable PII patterns                        |
| `mask_value()`     | Apply type-specific masking                           |
| `detect_pii()`     | Locate PII occurrences inside a value                 |
| `contains_pii()`   | Report whether a value matches any PII pattern        |
| `anonymize_text()` | Detect and mask PII inside text                       |
| `anonymize_data()` | Mask PII values while preserving all other values     |

The key behavior is that **PII is anonymized whenever a value matches one of the PII patterns**, so no column names are hard coded and unrelated fields such as `name` are not accidentally modified.

---

# 23. Human-in-the-Loop Confirmation for DML/DDL Tools

## 23.1 Problem

Every mutating tool previously ran the moment the agent called it. An agent that
misjudges a `DELETE` scope, or invents a table name, destroys data with no human
in the loop.

## 23.2 Mechanism

The server now blocks every mutating tool behind an MCP **elicitation**
(`elicitation/create`). Before the tool function runs, the server asks the
connected client to render an approval prompt carrying the actual target, the
values, and the risk label. The `tools/call` request stays pending until the
human answers.

The gate lives in `src/confirmation.py` and is registered as **server
middleware**, not inside the tools:

```python
mcp = MCPServer(
    "PostgreSQL MCP",
    middleware=[ConfirmationMiddleware(confirmation_settings)],
)
```

Middleware runs ahead of every `tools/call`, which has two consequences worth
noting:

* the 23 tool functions keep their current signatures, so the test suite can
  still call them directly as plain synchronous Python functions;
* the check is a single choke point, so a mutating tool added later is guarded
  by adding its name to `MUTATING_TOOLS` — there is no per-tool code to repeat.

## 23.3 Guarded tools

`MUTATING_TOOLS` covers the DML and DDL families:

| Family    | Tools                                                                                                                                        |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| DML       | `insert_row`, `insert_rows`, `update_rows`, `delete_rows`, `upsert_row`, `anonymize_and_insert`, `anonymize_and_insert_rows`, `anonymized_update`, `anonymized_delete` |
| DDL       | `create_table`, `delete_table`, `alter_table`, `create_database`, `delete_database`                                                           |

The read-only tools (`read_table`, `query`, `describe_table`, …) pass straight
through and never prompt.

Two secondary sets drive the wording of the prompt: `DESTRUCTIVE_TOOLS`
(`delete_*`, `alter_table`) and `ANONYMIZING_TOOLS`, which notes that PII is
masked on the way in.

## 23.4 Failure modes

The gate fails **closed** in every ambiguous case:

| Situation                                       | Behaviour                                                     |
| ----------------------------------------------- | ------------------------------------------------------------- |
| User answers "approve"                          | The tool runs.                                                |
| User answers "cancel"/"decline", or dismisses   | Tool never runs; agent gets `isError` with a decline message. |
| Client omits the checkbox (empty answer)        | Treated as a decline — the field defaults to `false`.         |
| Client never advertises `elicitation`           | Refused with an explanatory error.                            |
| Client supports URL mode but not form mode      | Refused (a form request would fail at protocol level).         |
| Elicitation raises mid-prompt                   | Refused; the write does not happen.                            |

Denials return a `CallToolResult` with `is_error` set rather than a
JSON-RPC-level error, so the agent can read the reason and adjust.

## 23.5 Configuration

| Variable                        | Default | Effect                                                                |
| -------------------------------- | ------- | --------------------------------------------------------------------- |
| `PG_MCP_CONFIRM_DML`             | `1`     | `0`/`false`/`off` disables the gate. Trusted single-user setups only.  |
| `PG_MCP_DML_ALLOWLIST`           | empty   | Comma-separated tool names that skip the prompt.                      |
| `PG_MCP_DML_ALLOW_NO_ELICITATION`| `0`     | `1` lets a client with no elicitation support write unattended.        |

Both flags accept `1/true/yes/on` and `0/false/no/off`; anything else logs a
warning and falls back to the default.

## 23.6 Tests

| File                             | Scope                                                                |
| -------------------------------- | -------------------------------------------------------------------- |
| `tests/test_dml_confirmation.py` | 81 unit tests over settings, capability detection, the gate, prompts. |
| `tests/test_confirmation_e2e.py` | 6 end-to-end tests over a live JSON-RPC session and a real database.  |

The end-to-end tests drive the server through a genuine MCP client session and
assert on real database effects: an approved insert lands a row, a declined
`delete_table` leaves the table intact, an approved one removes it, and a client
that advertises no elicitation capability is refused.
