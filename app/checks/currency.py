"""Which currency an offer's price is in, and what it is worth in the tender's currency.

An offer prints its currency however it likes: HK$, US$ 7.22, USD, C$, A$, EUR, €, RMB.
`read` turns that into an ISO 4217 code. Two things are never guessed:

- a sign several currencies share ("$", "dollars", "¥") counts only when the tender's own
  currency is one of them, and the row then says what it was taken as;
- a currency this table does not know stays unknown, unless the tender gives a rate for it.

Conversion needs the tender's currency and a rate for the offer's currency into it (the
rule set's `exchange_rates` slot, or PRICING_FX_RATES). There is no 1:1 fallback: an offer
that cannot be converted is not ranked, and its row says why."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ISO code -> how the Price Summary prints it.
LABELS = {"HKD": "HK$", "USD": "US$", "CAD": "C$", "AUD": "A$", "NZD": "NZ$", "SGD": "S$", "TWD": "NT$",
          "CNY": "RMB", "EUR": "€", "GBP": "£", "JPY": "JPY", "CHF": "CHF", "MOP": "MOP$"}

# A "$" with letters in front of it: the letters name the currency.
_DOLLAR_PREFIXES = {"hk": "HKD", "us": "USD", "c": "CAD", "ca": "CAD", "can": "CAD", "a": "AUD", "au": "AUD",
                    "nz": "NZD", "s": "SGD", "nt": "TWD", "mop": "MOP"}
# Words and codes, matched whole (a trailing "s" allowed).
_WORDS = {"hkd": "HKD", "hong kong dollar": "HKD", "usd": "USD", "us dollar": "USD", "united states dollar": "USD",
          "cad": "CAD", "canadian dollar": "CAD", "aud": "AUD", "australian dollar": "AUD", "nzd": "NZD",
          "new zealand dollar": "NZD", "sgd": "SGD", "singapore dollar": "SGD", "twd": "TWD", "new taiwan dollar": "TWD",
          "cny": "CNY", "rmb": "CNY", "renminbi": "CNY", "yuan": "CNY", "eur": "EUR", "euro": "EUR", "gbp": "GBP",
          "pound sterling": "GBP", "jpy": "JPY", "yen": "JPY", "chf": "CHF", "swiss franc": "CHF", "mop": "MOP", "pataca": "MOP"}
_SIGNS = {"€": "EUR", "£": "GBP"}
# Signs that more than one currency uses, and which.
_SHARED = {"$": {"HKD", "USD", "CAD", "AUD", "NZD", "SGD", "TWD", "MOP"}, "dollar": {"HKD", "USD", "CAD", "AUD", "NZD", "SGD", "TWD"},
           "¥": {"JPY", "CNY"}}


def label(code: str | None) -> str:
    """How a currency is printed in a row, a remark and a report."""
    return LABELS.get(code or "", code or "")


@dataclass(frozen=True)
class Reading:
    printed: str                  # as the offer printed it
    code: str | None = None       # ISO 4217, when it is clear
    shared: frozenset = frozenset()   # the candidates, when only a shared sign was printed
    mixed: bool = False           # two currencies printed ("HK$ ... (US$ ...)")

    @property
    def problem(self) -> str | None:
        if self.code:
            return None
        if not self.printed:
            return "not stated"
        return "mixed" if self.mixed else "ambiguous" if self.shared else "unknown"


def read(text: Any, known: tuple[str, ...] = ()) -> Reading:
    """The currency a price was printed in. `known` adds codes the tender gives a rate for."""
    printed = str(text or "").strip()
    s = " " + re.sub(r"\s+", " ", re.sub(r"\.", "", printed.lower())) + " "   # "U.S.$" reads as "us$"
    codes: list[str] = []

    def take(pattern: str, code: str) -> None:
        nonlocal s
        if re.search(pattern, s):
            codes.append(code)
            s = re.sub(pattern, " ", s)

    for prefix in sorted(_DOLLAR_PREFIXES, key=len, reverse=True):
        take(rf"(?<![a-z]){prefix}\s?\$", _DOLLAR_PREFIXES[prefix])
    for word in sorted(_WORDS, key=len, reverse=True):
        take(rf"(?<![a-z]){word}s?(?![a-z])", _WORDS[word])
    for extra in known:
        if extra.upper() not in LABELS:
            take(rf"(?<![a-z]){re.escape(extra.lower())}(?![a-z])", extra.upper())
    for sign, code in _SIGNS.items():
        take(re.escape(sign), code)
    if len(set(codes)) == 1:
        return Reading(printed, codes[0])
    if codes:                                                   # "HK$ ... (US$ ...)": two currencies
        return Reading(printed, None, frozenset(codes), mixed=True)
    shared = set()
    for sign, candidates in _SHARED.items():
        if re.search(re.escape(sign) if not sign.isalpha() else rf"(?<![a-z]){sign}s?(?![a-z])", s):
            shared |= candidates
    return Reading(printed, None, frozenset(shared))


def code_of(text: Any) -> str | None:
    """An ISO code from a setting that names a currency ("HK$", "HKD", "euro"), or None."""
    return read(text).code or (str(text).strip().upper() if re.fullmatch(r"[A-Za-z]{3}", str(text or "").strip()) else None)


@dataclass(frozen=True)
class Converted:
    code: str | None              # the offer's currency, when known
    rate: float | None            # into the tender's currency; None when it cannot be converted
    note: str = ""                # what the row says about it


def convert(reading: Reading, base: str | None, rates: dict[str, float]) -> Converted:
    """The rate that takes this offer's price into the tender's currency, and the note its row carries."""
    code = reading.code
    if code is None and base and (not reading.printed or (base in reading.shared and not reading.mixed)):
        how = "no currency printed" if not reading.printed else f"'{reading.printed}'"
        return Converted(base, 1.0, f"{how}; taken as {label(base)}, the tender's currency")
    if code is None:
        why = {"not stated": "no currency printed",
               "ambiguous": f"'{reading.printed}' could be {', '.join(label(c) for c in sorted(reading.shared))}",
               "mixed": f"'{reading.printed}' names more than one currency",
               "unknown": f"currency '{reading.printed}' not recognised"}[reading.problem]
        return Converted(None, None, f"{why}; not ranked until a reviewer corrects the currency")
    if base is None:
        return Converted(code, None, f"quoted in {label(code)}, but the tender's currency is not set, so it is not ranked")
    if code == base:
        return Converted(code, 1.0)
    if code not in rates:
        return Converted(code, None, f"quoted in {label(code)}; no exchange rate from {label(code)} to {label(base)} is set, "
                                     "so it is not ranked")
    return Converted(code, rates[code], f"quoted in {label(code)}, converted at {rates[code]:g} {label(base)}/{label(code)}")
