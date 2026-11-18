"""Deterministic format checks for Indian vendor identifiers.

Rule of thumb for this project: anything that CAN be checked with a rule IS
checked with a rule. AI is only used for reading documents and writing messages.
"""
import re

GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# GST state codes -> state name (subset used by the demo + common ones)
STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "19": "West Bengal", "23": "Madhya Pradesh", "24": "Gujarat", "27": "Maharashtra",
    "29": "Karnataka", "32": "Kerala", "33": "Tamil Nadu", "36": "Telangana", "37": "Andhra Pradesh",
}

# IFSC bank prefixes we recognise (a real build would call an IFSC directory API)
IFSC_BANKS = {
    "HDFC": "HDFC Bank", "ICIC": "ICICI Bank", "SBIN": "State Bank of India",
    "UTIB": "Axis Bank", "KKBK": "Kotak Mahindra Bank", "YESB": "Yes Bank",
    "PUNB": "Punjab National Bank", "IDFB": "IDFC First Bank",
}

PAN_HOLDER_TYPES = {"C": "Company", "P": "Individual", "F": "Firm/LLP", "H": "HUF",
                    "A": "AOP", "T": "Trust", "B": "BOI", "G": "Government", "L": "Local authority", "J": "Artificial juridical person"}

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com"}


def gstin_checksum(first14: str) -> str:
    """Official GSTIN check-digit algorithm (mod 36, alternating weights 1/2)."""
    total = 0
    for i, ch in enumerate(first14):
        val = GST_CHARS.index(ch)
        prod = val * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return GST_CHARS[(36 - total % 36) % 36]


def check_gstin(gstin: str) -> tuple[bool, str]:
    g = (gstin or "").strip().upper()
    if len(g) != 15:
        return False, f"GSTIN must be 15 characters (got {len(g)})"
    if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", g):
        return False, "GSTIN pattern is invalid (expected 2 digits + PAN + entity no. + 'Z' + check digit)"
    if g[:2] not in STATE_CODES and not (1 <= int(g[:2]) <= 38):
        return False, f"Unknown GST state code {g[:2]}"
    expected = gstin_checksum(g[:14])
    if g[14] != expected:
        return False, f"GSTIN check digit is wrong (expected '{expected}', got '{g[14]}') — likely a typo"
    return True, "Valid GSTIN"


def check_pan(pan: str) -> tuple[bool, str]:
    p = (pan or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", p):
        return False, "PAN must be 5 letters + 4 digits + 1 letter"
    return True, f"Valid PAN (holder type: {PAN_HOLDER_TYPES.get(p[3], 'Unknown')})"


def check_ifsc(ifsc: str) -> tuple[bool, str]:
    i = (ifsc or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", i):
        return False, "IFSC must be 4 letters + '0' + 6 characters"
    bank = IFSC_BANKS.get(i[:4])
    if not bank:
        return False, f"Unrecognised bank code '{i[:4]}'"
    return True, f"Valid IFSC ({bank})"


def check_email(email: str) -> tuple[bool, str]:
    e = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", e):
        return False, "Email address is invalid"
    if e.split("@")[1] in FREE_EMAIL_DOMAINS:
        return True, "Valid, but a free email domain (not a company domain)"
    return True, "Valid business email"


def pan_from_gstin(gstin: str) -> str:
    return (gstin or "").strip().upper()[2:12]


def state_from_gstin(gstin: str) -> str | None:
    return STATE_CODES.get((gstin or "").strip()[:2])
