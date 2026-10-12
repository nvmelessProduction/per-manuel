"""Parsing dei messaggi del canale Telegram (segnali e aggiornamenti).

Formato di esempio di un segnale:

    SEERSFX · SEGNALE ORO
    🔴 VENDI ORO (XAUUSD)
    📍 Zona d'ingresso: 4170 – 4175
    🛑 Stop Loss: 4180
    🎯 Take Profit 1: 4160
    🎯 Take Profit 2: 4150

Esempio di aggiornamento (di solito in risposta al segnale):

    SEERSFX · AGGIORNAMENTO
    ✅ Operazione in corso
    🔴 ORO in vendita: 55 pips a favore
    🔒 Metti in sicurezza parte dei profitti e porta lo stop a pareggio (BE+).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Nomi "parlati" degli strumenti -> simbolo standard
SYMBOL_ALIASES = {
    "ORO": "XAUUSD",
    "GOLD": "XAUUSD",
    "ARGENTO": "XAGUSD",
    "SILVER": "XAGUSD",
    "PETROLIO": "USOIL",
    "NASDAQ": "NAS100",
    "DAX": "GER40",
    "BITCOIN": "BTCUSD",
}

NUM = r"(\d+(?:[.,]\d+)?)"
DASH = r"\s*[-–—/]\s*"


@dataclass
class Signal:
    side: str  # "BUY" o "SELL"
    symbol: str  # simbolo standard (es. XAUUSD), prima della mappatura broker
    entry_low: float
    entry_high: float
    sl: float
    tps: list[float] = field(default_factory=list)

    @property
    def entry_mid(self) -> float:
        return (self.entry_low + self.entry_high) / 2


@dataclass
class Update:
    close_all: bool = False
    partial_close: bool = False
    breakeven: bool = False
    new_sl: float | None = None

    def is_empty(self) -> bool:
        return not (self.close_all or self.partial_close or self.breakeven or self.new_sl is not None)


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def _normalize(text: str) -> str:
    # Maiuscolo e apostrofi uniformati; le emoji non danno fastidio alle regex.
    return text.upper().replace("’", "'")


def _find_symbol(t: str) -> str | None:
    m = re.search(r"\(\s*([A-Z][A-Z0-9]{2,9})\s*\)", t)
    if m:
        return m.group(1)
    m = re.search(r"\b([A-Z]{3}(?:USD|EUR|JPY|GBP|CHF|CAD|AUD|NZD))\b", t)
    if m:
        return m.group(1)
    for alias, sym in SYMBOL_ALIASES.items():
        if re.search(rf"\b{alias}\b", t):
            return sym
    return None


def _find_side(t: str) -> str | None:
    if re.search(r"\b(VENDI|VENDERE|SELL|SHORT)\b", t):
        return "SELL"
    if re.search(r"\b(COMPRA|COMPRARE|ACQUISTA|BUY|LONG)\b", t):
        return "BUY"
    return None


def parse_signal(text: str) -> Signal | None:
    """Ritorna un Signal se il messaggio è un segnale completo e coerente, altrimenti None."""
    t = _normalize(text)

    side = _find_side(t)
    symbol = _find_symbol(t)
    if not side or not symbol:
        return None

    m = re.search(r"STOP\s*LOSS\s*[:=]?\s*" + NUM, t) or re.search(r"\bSL\s*[:=]?\s*" + NUM, t)
    if not m:
        return None
    sl = _to_float(m.group(1))

    tps = [_to_float(x) for x in re.findall(r"(?:TAKE\s*PROFIT|\bTP)\s*\d*\s*[:=]\s*" + NUM, t)]
    if not tps:
        return None

    m = re.search(r"(?:INGRESSO|ENTRATA|ENTRY)[^0-9\n]*" + NUM + r"(?:" + DASH + NUM + r")?", t)
    if not m:
        return None
    a = _to_float(m.group(1))
    b = _to_float(m.group(2)) if m.group(2) else a
    low, high = min(a, b), max(a, b)

    # Controllo di coerenza dei livelli
    if side == "SELL":
        if not (sl > high and all(tp < low for tp in tps)):
            return None
        tps.sort(reverse=True)  # TP1 è il più vicino
    else:
        if not (sl < low and all(tp > high for tp in tps)):
            return None
        tps.sort()

    return Signal(side=side, symbol=symbol, entry_low=low, entry_high=high, sl=sl, tps=tps)


def parse_update(text: str) -> Update | None:
    """Ritorna un Update se il messaggio contiene istruzioni di gestione, altrimenti None."""
    t = _normalize(text)
    u = Update()

    if re.search(r"PAREGGIO|BREAK\s*-?\s*EVEN|\bBE\b\+?", t):
        u.breakeven = True

    if re.search(r"PARZIAL|PARTE DEI PROFITTI|IN SICUREZZA|PARTIAL", t):
        u.partial_close = True

    if not u.partial_close and re.search(
        r"\bCHIUDI\b|\bCHIUDERE\b|CHIUDIAMO|CHIUSURA TOTALE|\bCLOSE ALL\b|\bCLOSE NOW\b|ESCI\b|USCIAMO", t
    ):
        u.close_all = True

    if not u.breakeven:
        m = re.search(r"(?:STOP|SL)[^0-9\n]{0,30}?\bA\s+" + NUM, t)
        if m:
            u.new_sl = _to_float(m.group(1))

    return None if u.is_empty() else u
