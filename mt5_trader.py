"""Esecuzione degli ordini su MetaTrader 5 (gira solo su Windows con il terminale MT5 installato)."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from types import SimpleNamespace

from signal_parser import Signal, Update

log = logging.getLogger("mt5")

try:
    import MetaTrader5 as mt5
except ImportError:  # permette di testare il parser anche fuori da Windows
    mt5 = None


# Nomi alternativi usati dai broker per lo stesso strumento
SYMBOL_ALTERNATIVES = {
    "XAUUSD": ["GOLD"],
    "XAGUSD": ["SILVER"],
    "NAS100": ["USTEC", "US100", "NDX100", "NASDAQ"],
    "GER40": ["DE40", "GER30", "DAX40", "DE30"],
    "USOIL": ["WTI", "XTIUSD", "USOUSD"],
}


def find_broker_symbol(name: str) -> str | None:
    """Trova il nome usato dal broker (es. XAUUSD -> XAUUSD.m, XAUUSD+, GOLD).

    Preferisce simboli negoziabili, poi la corrispondenza esatta, poi il nome più corto."""
    names = [name.upper()] + SYMBOL_ALTERNATIVES.get(name.upper(), [])
    candidates = []
    for s in mt5.symbols_get() or []:
        up = s.name.upper()
        for rank, n in enumerate(names):
            # suffissi ammessi: XAUUSD.m, XAUUSD+, XAUUSD_i, XAUUSDm (minuscolo), non XAUUSDX
            if up == n or (up.startswith(n) and len(up) <= len(n) + 4 and not s.name[len(n)].isupper()):
                tradable = s.trade_mode != 0  # 0 = SYMBOL_TRADE_MODE_DISABLED
                candidates.append((not tradable, rank, up != n, len(up), s.name))
                break
    return min(candidates)[-1] if candidates else None


# Modalità a posizione singola (la gestione dopo l'apertura la fa il bot):
#   tp1_be        +X pips: parziale + stop al prezzo di entrata          TP finale = ultimo TP
#   tp1_trailing  +X pips: parziale + trailing stop                      TP finale = ultimo TP
#   pips_be_tp1   +X pips: parziale + stop al prezzo di entrata          TP finale = TP1
#   pips_be_trail +X pips: parziale + stop al prezzo di entrata; al TP1 parte il trailing stop, nessun TP
SINGLE_MODES = ("tp1_be", "tp1_trailing", "pips_be_tp1", "pips_be_trail")


def final_tp(mode: str, tps: list[float]) -> float:
    """TP da mettere sulla posizione (0 = nessun TP)."""
    if not tps or mode == "pips_be_trail":
        return 0.0
    return tps[0] if mode == "pips_be_tp1" else tps[-1]


class Trader:
    def __init__(self, mt5_cfg: dict, trading_cfg: dict, state_file: str = "state.json"):
        self.mt5_cfg = mt5_cfg
        self.cfg = trading_cfg
        self.dry_run = bool(trading_cfg.get("dry_run", True))
        self.magic = int(trading_cfg.get("magic", 260412))
        self.state_file = state_file
        self.lock = threading.Lock()
        # state = {"signals": {msg_id: {"symbol", "side", "tickets": [...], "entry": float}}, "last_signal": msg_id}
        self.state = {"signals": {}, "last_signal": None}
        self._symbol_cache: dict[str, str] = {}
        # "tp1_be": 1 posizione, al TP1 chiude una parte e mette a pareggio, TP finale = ultimo TP
        # "tp1_trailing": come sopra ma al posto del pareggio parte un trailing stop
        # "two_positions": una posizione per ogni TP
        self.management = trading_cfg.get("management", "two_positions")
        self.single_mode = self.management in SINGLE_MODES
        self._load_state()

    # ------------------------------------------------------------------ setup
    def connect(self, attempts: int = 6) -> None:
        if mt5 is None:
            raise RuntimeError("Libreria MetaTrader5 non installata (pip install MetaTrader5, solo Windows).")
        kwargs = {"timeout": 120000}
        if self.mt5_cfg.get("path"):
            kwargs["path"] = self.mt5_cfg["path"]
        if self.mt5_cfg.get("portable"):
            kwargs["portable"] = True  # copia di MT5 dedicata, con i suoi dati nella sua cartella
        if self.mt5_cfg.get("login"):
            kwargs["login"] = int(self.mt5_cfg["login"])
            kwargs["password"] = self.mt5_cfg.get("password", "")
            kwargs["server"] = self.mt5_cfg.get("server", "")
        # Dopo un riavvio della VPS il terminale può metterci un po' a partire: riprovo
        for i in range(1, attempts + 1):
            if mt5.initialize(**kwargs) and mt5.account_info() is not None:
                break
            log.warning("Connessione a MT5 non riuscita (%s), tentativo %d/%d", mt5.last_error(), i, attempts)
            mt5.shutdown()
            time.sleep(10)
        else:
            raise RuntimeError(f"Impossibile collegarsi a MT5: {mt5.last_error()}")
        info = mt5.account_info()
        log.info("Connesso a MT5: conto %s (%s), saldo %.2f %s", info.login, info.server, info.balance, info.currency)
        if not mt5.terminal_info().trade_allowed:
            log.warning("ATTENZIONE: 'Algo Trading' è disattivato nel terminale MT5, gli ordini verranno rifiutati.")

    def ensure_connected(self) -> None:
        """Se il terminale si è chiuso o ha perso la connessione, mi ricollego."""
        if mt5.terminal_info() is None or mt5.account_info() is None:
            log.warning("Connessione a MT5 persa, mi ricollego...")
            mt5.shutdown()
            self.connect()

    def shutdown(self) -> None:
        if mt5 is not None:
            mt5.shutdown()

    # ------------------------------------------------------------------ stato
    def _load_state(self) -> None:
        if os.path.exists(self.state_file):
            with open(self.state_file, encoding="utf-8") as f:
                self.state = json.load(f)

    def _save_state(self) -> None:
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)
        os.replace(tmp, self.state_file)

    def has_signal(self, msg_id: int) -> bool:
        return str(msg_id) in self.state["signals"]

    # ------------------------------------------------------------------ util
    def broker_symbol(self, symbol: str) -> str:
        if symbol in self.cfg.get("symbol_map", {}):
            return self.cfg["symbol_map"][symbol] + self.cfg.get("symbol_suffix", "")
        if self.cfg.get("symbol_suffix"):
            return symbol + self.cfg["symbol_suffix"]
        if symbol not in self._symbol_cache:
            found = find_broker_symbol(symbol)
            if found and found != symbol:
                log.info("Simbolo %s -> %s sul broker", symbol, found)
            self._symbol_cache[symbol] = found or symbol
        return self._symbol_cache[symbol]

    def _calc_lots(self, sym: str, info, order_type: int, entry: float, sl: float, legs: int,
                   min_lot: float | None = None) -> float:
        """Lotto per singola gamba (una gamba per ogni TP)."""
        step = info.volume_step
        min_lot = max(min_lot or 0, info.volume_min)
        if self.cfg.get("lot_mode", "fixed") == "risk":
            balance = mt5.account_info().balance
            risk_money = balance * float(self.cfg.get("risk_percent", 1.0)) / 100
            loss_per_lot = abs(mt5.order_calc_profit(order_type, sym, 1.0, entry, sl) or 0)
            if loss_per_lot <= 0:
                log.warning("Impossibile calcolare il rischio per lotto -> uso il lotto minimo %s", min_lot)
                return round(min_lot, 8)
            per_leg = risk_money / loss_per_lot / legs
        else:
            per_leg = float(self.cfg.get("fixed_lot", 0.01))
        per_leg = min(per_leg, float(self.cfg.get("max_lot_per_leg", 1.0)), info.volume_max)
        per_leg = math.floor(per_leg / step + 1e-9) * step
        if per_leg < min_lot:
            log.warning("Il rischio impostato richiederebbe meno del lotto minimo -> apro il lotto minimo %s "
                        "(il rischio reale sarà più alto)", min_lot)
            per_leg = min_lot
        return round(per_leg, 8)

    def _send(self, request: dict):
        if self.dry_run:
            log.info("[DRY RUN] order_send %s", request)
            return SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, order=0, comment="dry run")
        # Prova le varie modalità di filling finché il broker non ne accetta una
        fillings = [request["type_filling"]] if "type_filling" in request else [
            mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
        res = None
        for filling in fillings:
            req = dict(request, type_filling=filling)
            res = mt5.order_send(req)
            if res is None:
                log.error("order_send ha ritornato None: %s", mt5.last_error())
                return None
            if res.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
                break
        if res.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            log.error("Ordine rifiutato: retcode=%s %s | %s", res.retcode, res.comment, request)
        return res

    @staticmethod
    def _ok(res) -> bool:
        return res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)

    # ------------------------------------------------------------------ apertura
    def open_signal(self, msg_id: int, sig: Signal) -> None:
        with self.lock:
            if self.has_signal(msg_id):
                log.info("Segnale %s già eseguito, ignoro", msg_id)
                return
            self.ensure_connected()
            # Il canale ha mandato prima "VENDI ORO" e ora, in un messaggio nuovo, i livelli:
            # non apro un secondo trade, aggiungo SL/TP a quello appena aperto.
            if sig.complete:
                prev = self._recent_without_levels(sig)
                if prev is not None:
                    log.info("Messaggio %s: livelli per il trade del messaggio %s, li applico", msg_id, prev)
                    self._apply_levels(prev, sig)
                    return
            self._open_signal(msg_id, sig)

    def price_in_zone(self, sig: Signal) -> bool:
        """Il prezzo attuale è dentro la zona d'ingresso (± tolleranza) e non oltre SL/TP1?"""
        if sig.entry_low is None:
            return False
        with self.lock:
            self.ensure_connected()
            sym = self.broker_symbol(sig.symbol)
            if not mt5.symbol_select(sym, True):
                return False
            info, tick = mt5.symbol_info(sym), mt5.symbol_info_tick(sym)
            tol = float(self.cfg.get("entry_tolerance_points", 200)) * info.point
            price = tick.ask if sig.side == "BUY" else tick.bid
            log.info("Prezzo attuale %s, zona d'ingresso %s - %s (tolleranza %s)", price, sig.entry_low, sig.entry_high, tol)
            return sig.entry_low - tol <= price <= sig.entry_high + tol

    def _recent_without_levels(self, sig: Signal) -> str | None:
        window = float(self.cfg.get("merge_levels_minutes", 15)) * 60
        sym = self.broker_symbol(sig.symbol)
        for sid, rec in reversed(list(self.state["signals"].items())):
            if (rec.get("levels_missing") and rec["symbol"] == sym and rec["side"] == sig.side
                    and time.time() - rec.get("opened_at", 0) < window):
                return sid
        return None

    def _open_signal(self, msg_id: int, sig: Signal) -> None:
        sym = self.broker_symbol(sig.symbol)
        if not mt5.symbol_select(sym, True):
            log.error("Simbolo %s non trovato sul broker (controlla symbol_map / symbol_suffix)", sym)
            return
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        point, digits = info.point, info.digits
        tol = float(self.cfg.get("entry_tolerance_points", 200)) * point
        buy = sig.side == "BUY"
        price = tick.ask if buy else tick.bid

        # Prezzo già oltre lo stop o oltre il TP1? Segnale non più valido.
        beyond_sl = sig.sl is not None and (price <= sig.sl if buy else price >= sig.sl)
        beyond_tp = bool(sig.tps) and (price >= sig.tps[0] if buy else price <= sig.tps[0])
        if beyond_sl or beyond_tp:
            log.warning("Segnale %s scartato: prezzo attuale %s fuori dai livelli (SL %s, TP %s)",
                        msg_id, price, sig.sl, sig.tps)
            return

        market = self.cfg.get("entry_mode", "market") == "market" or sig.entry_low is None
        in_zone = market or (price <= sig.entry_high + tol if buy else price >= sig.entry_low - tol)
        if in_zone:
            action, order_type, entry = mt5.TRADE_ACTION_DEAL, (mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL), price
        elif self.cfg.get("use_pending_orders", True):
            # Prezzo non ancora in zona: limit sul bordo più vicino della zona
            entry = sig.entry_high if buy else sig.entry_low
            action, order_type = mt5.TRADE_ACTION_PENDING, (mt5.ORDER_TYPE_BUY_LIMIT if buy else mt5.ORDER_TYPE_SELL_LIMIT)
        else:
            log.warning("Segnale %s: prezzo %s fuori zona %s-%s, ordini pendenti disattivati -> ignoro",
                        msg_id, price, sig.entry_low, sig.entry_high)
            return

        if self.management == "market_limit":
            self._open_market_limit(msg_id, sig, sym, info, tick, buy)
            return

        single = self.single_mode
        if single:
            # Una sola posizione con TP finale; la parziale + BE/trailing la gestisce il manager.
            # Lotto minimo = 2 x minimo del broker, così la chiusura parziale è sempre possibile.
            tps = [final_tp(self.management, sig.tps)]
            min_lot = 2 * info.volume_min
        else:
            tps = sig.tps[: int(self.cfg.get("max_tps", len(sig.tps)))] or [0.0]
            min_lot = None
        if sig.sl is None and self.cfg.get("lot_mode", "fixed") == "risk":
            # senza stop loss non posso calcolare il rischio: apro il minimo
            lots = round(max(min_lot or 0, info.volume_min), 8)
            log.info("Segnale %s senza stop loss: apro il lotto minimo %s", msg_id, lots)
        else:
            lots = self._calc_lots(sym, info, order_type if action == mt5.TRADE_ACTION_DEAL else
                                   (mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL), entry,
                                   sig.sl if sig.sl is not None else 0, len(tps), min_lot)
        log.info("Segnale %s: %s %s x%d gambe da %.2f lotti @ %s, SL %s, TP %s",
                 msg_id, sig.side, sym, len(tps), lots, entry, sig.sl, tps)

        tickets = []
        for i, tp in enumerate(tps, start=1):
            req = {
                "action": action,
                "symbol": sym,
                "volume": lots,
                "type": order_type,
                "price": round(entry, digits),
                "sl": round(sig.sl, digits) if sig.sl is not None else 0.0,
                "tp": round(tp, digits),
                "deviation": int(self.cfg.get("deviation_points", 50)),
                "magic": self.magic,
                "comment": f"sfx{msg_id}-{'M' if single else 'TP%d' % i}",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_filling"] = mt5.ORDER_FILLING_RETURN
                expiry_min = int(self.cfg.get("pending_expiry_minutes", 0))
                if expiry_min > 0:
                    req["type_time"] = mt5.ORDER_TIME_SPECIFIED
                    req["expiration"] = int(tick.time) + expiry_min * 60
            res = self._send(req)
            if self._ok(res):
                tickets.append(res.order)
                log.info("  posizione %d/%d aperta, ticket %s", i, len(tps), res.order)

        if tickets:
            self.state["signals"][str(msg_id)] = {
                "symbol": sym, "side": sig.side, "tickets": tickets, "entry": entry, "dry_run": self.dry_run,
                "mode": self.management if single else "two_positions",
                "tp1": sig.tps[0] if sig.tps else None, "levels_missing": not sig.complete,
                "opened_at": time.time(), "partial_done": False, "trailing": False, "closed": False}
            self.state["last_signal"] = msg_id
            self._save_state()

    # ------------------------------------------------------------------ gestione
    def _positions(self, rec: dict):
        """Posizioni aperte e ordini pendenti appartenenti a un segnale."""
        tickets = set(rec["tickets"])
        pos = [p for p in (mt5.positions_get(symbol=rec["symbol"]) or [])
               if p.magic == self.magic and (p.identifier in tickets or p.ticket in tickets)]
        orders = [o for o in (mt5.orders_get(symbol=rec["symbol"]) or [])
                  if o.magic == self.magic and o.ticket in tickets]
        return pos, orders

    def _close_position(self, p, volume: float | None = None) -> None:
        tick = mt5.symbol_info_tick(p.symbol)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        self._send({
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "position": p.ticket,
            "volume": volume or p.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": int(self.cfg.get("deviation_points", 50)),
            "magic": self.magic,
            "comment": "sfx close",
        })

    def _modify_sl(self, p, new_sl: float) -> None:
        digits = mt5.symbol_info(p.symbol).digits
        self._send({
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": p.symbol,
            "position": p.ticket,
            "sl": round(new_sl, digits),
            "tp": p.tp,
            "magic": self.magic,
        })

    def _cancel_order(self, o) -> None:
        self._send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})

    def update_levels(self, msg_id: int, sig: Signal) -> None:
        """Il segnale originale è stato modificato: aggiorna SL/TP delle posizioni già aperte."""
        with self.lock:
            if str(msg_id) not in self.state["signals"]:
                return
            self.ensure_connected()
            self._apply_levels(str(msg_id), sig)

    def _apply_levels(self, sid: str, sig: Signal) -> None:
        rec = self.state["signals"][sid]
        if rec.get("dry_run"):
            log.info("[DRY RUN] livelli del segnale %s: SL %s TP %s", sid, sig.sl, sig.tps)
            return
        if rec.get("mode") == "market_limit":
            # gli stop sono fissi (100/50 pips dall'apertura): dal segnale prendo solo il TP1,
            # che il manager mette su tutte e due le operazioni
            if sig.tps:
                rec["tp1"] = sig.tps[0]
                log.info("Segnale %s: TP1 = %s per entrambe le operazioni", sid, sig.tps[0])
            if sig.complete:
                rec["levels_missing"] = False
            self._save_state()
            return
        pos, orders = self._positions(rec)
        digits = mt5.symbol_info(rec["symbol"]).digits
        single = rec.get("mode") in SINGLE_MODES
        if sig.tps:
            rec["tp1"] = sig.tps[0]
        if sig.complete:
            rec["levels_missing"] = False
        self._save_state()
        items = [(p, True) for p in pos] + [(o, False) for o in orders]
        for item, is_position in items:
            if single:
                tp = final_tp(rec["mode"], sig.tps) if sig.tps else item.tp
            else:
                key = item.identifier if is_position else item.ticket
                leg = rec["tickets"].index(key) + 1 if key in rec["tickets"] else 1
                tp = sig.tps[min(leg, len(sig.tps)) - 1] if sig.tps else item.tp
            # dopo la parziale lo stop lo gestisce il bot (pareggio/trailing): non lo tocco
            sl = item.sl if (sig.sl is None or (single and rec.get("partial_done"))) else sig.sl
            if is_position:
                req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": item.symbol, "position": item.ticket}
            else:
                req = {"action": mt5.TRADE_ACTION_MODIFY, "order": item.ticket, "price": item.price_open,
                       "type_time": item.type_time, "expiration": item.time_expiration}
            req.update({"sl": round(sl, digits), "tp": round(tp, digits), "magic": self.magic})
            log.info("Segnale %s: imposto livelli ticket %s -> SL %s TP %s", sid, item.ticket, sl, tp)
            self._send(req)

    def apply_update(self, upd: Update, reply_to: int | None) -> None:
        with self.lock:
            sig_id = str(reply_to) if reply_to and str(reply_to) in self.state["signals"] else (
                str(self.state["last_signal"]) if self.state["last_signal"] is not None else None)
            rec = self.state["signals"].get(sig_id) if sig_id else None
            if not rec:
                log.info("Aggiornamento ricevuto ma nessun segnale aperto a cui applicarlo")
                return
            follow = self.cfg.get("channel_updates", "close_only")
            if follow == "ignore" or (follow == "close_only" and not upd.close_all):
                log.info("Aggiornamento dal canale ignorato (la gestione la fa il bot): %s", upd)
                return
            self.ensure_connected()
            pos, orders = self._positions(rec)
            log.info("Aggiornamento per segnale %s: %s (posizioni %d, pendenti %d)", sig_id, upd, len(pos), len(orders))
            if self.dry_run and rec.get("dry_run"):
                log.info("[DRY RUN] nessuna posizione reale da gestire")
                return

            if upd.close_all:
                for p in pos:
                    self._close_position(p)
                for o in orders:
                    self._cancel_order(o)
                return

            # Istruzioni di gestione su un trade mai entrato: cancello i pendenti
            if orders and (upd.breakeven or upd.partial_close):
                for o in orders:
                    log.info("Cancello ordine pendente %s (il trade è già in gestione)", o.ticket)
                    self._cancel_order(o)

            if rec.get("mode") in SINGLE_MODES:
                for p in pos:
                    if upd.partial_close and not rec.get("partial_done"):
                        # il canale dice di mettere in sicurezza prima del TP1: stessa gestione del TP1
                        self._secure(rec, p, "aggiornamento dal canale")
                    elif upd.breakeven:
                        self._breakeven(p)
                    if upd.new_sl is not None and not upd.breakeven:
                        if rec.get("partial_done"):
                            self._modify_sl_if_better(p, upd.new_sl)
                        else:
                            self._modify_sl(p, upd.new_sl)
                return

            if upd.partial_close and pos:
                if len(pos) > 1:
                    # chiudo la gamba col TP più vicino
                    buy = pos[0].type == mt5.POSITION_TYPE_BUY
                    nearest = min(pos, key=lambda p: p.tp if buy else -p.tp)
                    self._close_position(nearest)
                    pos = [p for p in pos if p.ticket != nearest.ticket]
                else:
                    p = pos[0]
                    info = mt5.symbol_info(p.symbol)
                    vol = p.volume * float(self.cfg.get("partial_close_percent", 50)) / 100
                    vol = math.floor(vol / info.volume_step + 1e-9) * info.volume_step
                    if vol >= info.volume_min and p.volume - vol >= info.volume_min:
                        self._close_position(p, round(vol, 8))
                    else:
                        log.info("Volume %.2f troppo piccolo per una chiusura parziale", p.volume)

            if upd.breakeven:
                for p in pos:
                    self._breakeven(p)
            elif upd.new_sl is not None:
                for p in pos:
                    self._modify_sl(p, upd.new_sl)

    # ------------------------------------------------------------------ gestione automatica TP1
    def pip_size(self, info) -> float:
        if self.cfg.get("pip_size"):
            return float(self.cfg["pip_size"])
        name = info.name.upper()
        if name.startswith(("XAU", "GOLD")):
            return 0.1          # oro: 1 pip = 0,10
        if name.startswith(("XAG", "SILVER")):
            return 0.01
        if info.digits in (3, 5):
            return info.point * 10  # forex: 1 pip = 10 punti
        return info.point

    def _modify_sl_if_better(self, p, new_sl: float) -> bool:
        """Sposta lo stop solo se lo migliora (mai indietro)."""
        buy = p.type == mt5.POSITION_TYPE_BUY
        if p.sl and ((buy and new_sl <= p.sl) or (not buy and new_sl >= p.sl)):
            return False
        res = self._send({
            "action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": p.ticket,
            "sl": round(new_sl, mt5.symbol_info(p.symbol).digits), "tp": p.tp, "magic": self.magic,
        })
        return self._ok(res)

    def _breakeven(self, p) -> None:
        # 0 = esattamente il prezzo di entrata dell'operazione
        off = float(self.cfg.get("breakeven_offset_pips", 0)) * self.pip_size(mt5.symbol_info(p.symbol))
        buy = p.type == mt5.POSITION_TYPE_BUY
        be = p.price_open + off if buy else p.price_open - off
        if self._modify_sl_if_better(p, be):
            log.info("Posizione %s: stop a pareggio (%s)", p.ticket, round(be, 5))

    def _partial_close(self, p) -> None:
        info = mt5.symbol_info(p.symbol)
        vol = p.volume * float(self.cfg.get("partial_close_percent", 50)) / 100
        vol = math.floor(vol / info.volume_step + 1e-9) * info.volume_step
        if vol >= info.volume_min and p.volume - vol >= info.volume_min - 1e-9:
            log.info("Posizione %s: chiudo %.2f lotti su %.2f", p.ticket, vol, p.volume)
            self._close_position(p, round(vol, 8))
        else:
            log.info("Posizione %s: volume %.2f troppo piccolo per la chiusura parziale", p.ticket, p.volume)

    def _secure(self, rec: dict, p, reason: str) -> None:
        """TP1: chiusura parziale + pareggio oppure avvio del trailing stop."""
        log.info("Segnale %s %s (%s): metto in sicurezza", rec["symbol"], p.ticket, reason)
        self._partial_close(p)
        rec["partial_done"] = True
        p = (mt5.positions_get(ticket=p.ticket) or [p])[0]
        if rec.get("mode") == "tp1_trailing":
            rec["trailing"] = True
            log.info("Posizione %s: avvio trailing stop di %s pips", p.ticket, self.cfg.get("trailing_pips", 3))
            self._trail(p)
        else:
            self._breakeven(p)
        self._save_state()

    def _trail(self, p, dist: float | None = None) -> None:
        """Sposta lo stop a `dist` dal prezzo (default: trailing_pips), solo a favore."""
        info = mt5.symbol_info(p.symbol)
        tick = mt5.symbol_info_tick(p.symbol)
        pip = self.pip_size(info)
        if dist is None:
            dist = float(self.cfg.get("trailing_pips", 3)) * pip
        dist = max(dist, (info.trade_stops_level + 1) * info.point)  # distanza minima imposta dal broker
        step = float(self.cfg.get("trailing_step_pips", 1)) * pip
        buy = p.type == mt5.POSITION_TYPE_BUY
        new_sl = tick.bid - dist if buy else tick.ask + dist
        if p.sl and ((buy and new_sl < p.sl + step) or (not buy and new_sl > p.sl - step)):
            return
        if self._modify_sl_if_better(p, new_sl):
            log.info("Posizione %s: trailing stop -> %s", p.ticket, round(new_sl, info.digits))

    def manage_positions(self) -> None:
        """Controlla le posizioni aperte: TP1 raggiunto -> parziale + pareggio/trailing."""
        changed = False
        for rec in self.state["signals"].values():
            if rec.get("mode") == "market_limit" and not rec.get("closed") and not rec.get("dry_run"):
                self._manage_market_limit(rec)
                continue
            if rec.get("mode") not in SINGLE_MODES or rec.get("closed") or rec.get("dry_run"):
                continue
            pos, orders = self._positions(rec)
            if not pos and not orders:
                rec["closed"] = True
                changed = True
                continue
            for p in pos:
                if not rec.get("partial_done"):
                    tick = mt5.symbol_info_tick(p.symbol)
                    buy = p.type == mt5.POSITION_TYPE_BUY
                    close_price = tick.bid if buy else tick.ask
                    if self.cfg.get("partial_trigger", "pips") == "pips":
                        # +X pips dal prezzo a cui il bot ha aperto davvero l'operazione
                        pips = float(self.cfg.get("partial_pips", 40))
                        dist = pips * self.pip_size(mt5.symbol_info(p.symbol))
                        target = p.price_open + dist if buy else p.price_open - dist
                        reason = f"+{pips:g} pips dall'apertura ({p.price_open} -> {round(target, 5)})"
                    else:
                        target = rec.get("tp1")
                        reason = f"TP1 {target} raggiunto"
                    if target and ((buy and close_price >= target) or (not buy and close_price <= target)):
                        self._secure(rec, p, reason)
                        p = (mt5.positions_get(ticket=p.ticket) or [p])[0]
                # pips_be_trail: quando il prezzo arriva al TP1 parte il trailing stop (solo a favore)
                if rec.get("mode") == "pips_be_trail" and not rec.get("trailing") and rec.get("tp1"):
                    tick = mt5.symbol_info_tick(p.symbol)
                    buy = p.type == mt5.POSITION_TYPE_BUY
                    close_price = tick.bid if buy else tick.ask
                    if (buy and close_price >= rec["tp1"]) or (not buy and close_price <= rec["tp1"]):
                        # Il trailing parte dallo stop attuale (il pareggio) e da qui in poi lo stop
                        # si muove di un pip per ogni pip che il mercato fa a favore.
                        start_sl = p.sl or p.price_open
                        rec["trail_dist"] = abs(close_price - start_sl)
                        log.info("Posizione %s: TP1 %s raggiunto, parte il trailing dallo stop %s "
                                 "(segue il prezzo a %.2f di distanza, solo a favore)",
                                 p.ticket, rec["tp1"], start_sl, rec["trail_dist"])
                        rec["trailing"] = True
                        changed = True
                if rec.get("trailing"):
                    self._trail(p, rec.get("trail_dist"))
        if changed:
            self._save_state()

    def start_manager(self, interval: float = 1.0) -> None:
        if not self.single_mode and self.management != "market_limit":
            return

        def loop():
            while True:
                time.sleep(interval)
                try:
                    with self.lock:
                        if mt5.terminal_info() is not None:
                            self.manage_positions()
                except Exception:
                    log.exception("Errore nella gestione automatica delle posizioni")

        threading.Thread(target=loop, daemon=True, name="manager").start()
        when = ("a +%s pips dall'apertura" % self.cfg.get("partial_pips", 40)
                if self.cfg.get("partial_trigger", "pips") == "pips" else "al TP1")
        trail = self.cfg.get("trailing_pips", 3)
        if self.management == "market_limit":
            c = self.cfg
            log.info("Gestione automatica attiva: 1) mercato %s lotti, SL %s pips, a +%s pips chiude il %s%% e pareggio, "
                     "TP=TP1 | 2) limit %s lotti a %s pips dallo stop, SL %s pips, a +%s pips chiude il %s%% e pareggio, "
                     "TP=TP1", c.get("a_lot", 0.02), c.get("a_sl_pips", 100), c.get("a_partial_pips", 30),
                     c.get("partial_close_percent", 50), c.get("b_lot", 0.04), c.get("b_offset_pips", 50),
                     c.get("b_sl_pips", 50), c.get("b_partial_pips", 40), c.get("partial_close_percent", 50))
            return
        log.info("Gestione automatica attiva: %s chiude il %s%% e %s", when, self.cfg.get("partial_close_percent", 50), {
            "tp1_be": "porta lo stop al prezzo di entrata (TP finale = ultimo TP)",
            "tp1_trailing": "avvia trailing stop di %s pips (TP finale = ultimo TP)" % trail,
            "pips_be_tp1": "porta lo stop al prezzo di entrata (TP finale = TP1)",
            "pips_be_trail": "porta lo stop al prezzo di entrata; dal TP1 lo stop segue il prezzo pip per pip, "
                             "senza TP",
        }[self.management])

    # ------------------------------------------------------------------ strategia "mercato + limit"
    # 1) A MERCATO   a_lot (0,02): SL a a_sl_pips (100) dall'apertura, TP = TP1 del segnale;
    #                a +a_partial_pips (30) chiude il 50% e porta lo stop all'entrata.
    # 2) LIMIT       b_lot (0,04) a b_offset_pips (50) dallo stop della prima operazione;
    #                SL a b_sl_pips (50) dall'apertura, TP = TP1 del segnale;
    #                a +b_partial_pips (40) chiude il 50% e porta lo stop all'entrata.
    # Finché non c'è stata la parziale il bot ricontrolla e rimette SL/TP giusti.
    def _ml_levels(self, leg: str, buy: bool, open_price: float, pip: float, tp1) -> tuple[float, float]:
        sl_pips = float(self.cfg.get("a_sl_pips", 100) if leg == "A" else self.cfg.get("b_sl_pips", 50))
        sl = open_price - sl_pips * pip if buy else open_price + sl_pips * pip
        return sl, (tp1 or 0.0)

    def _open_market_limit(self, msg_id: int, sig: Signal, sym: str, info, tick, buy: bool) -> None:
        pip, digits = self.pip_size(info), info.digits
        tp1 = sig.tps[0] if sig.tps else None
        a_lot = float(self.cfg.get("a_lot", 0.02))
        b_lot = float(self.cfg.get("b_lot", 0.04))
        dev = int(self.cfg.get("deviation_points", 50))

        # --- 1) operazione a mercato
        price = tick.ask if buy else tick.bid
        sl_a, tp = self._ml_levels("A", buy, price, pip, tp1)
        res = self._send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": a_lot,
            "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, "price": round(price, digits),
            "sl": round(sl_a, digits), "tp": round(tp, digits), "deviation": dev, "magic": self.magic,
            "comment": f"sfx{msg_id}-A", "type_time": mt5.ORDER_TIME_GTC,
        })
        if not self._ok(res):
            log.error("Segnale %s: operazione a mercato non aperta, non piazzo il limit", msg_id)
            return
        a_ticket = res.order
        if not self.dry_run:
            p = (mt5.positions_get(ticket=a_ticket) or [None])[0]
            if p is not None:
                price = p.price_open  # prezzo reale di esecuzione
                sl_a, _ = self._ml_levels("A", buy, price, pip, tp1)
        log.info("Segnale %s: 1) %s %s %.2f lotti a mercato @ %s, SL %s, TP %s", msg_id, sig.side, sym, a_lot,
                 price, round(sl_a, digits), tp1)

        # --- 2) ordine limit a b_offset_pips dallo stop della prima operazione
        off = float(self.cfg.get("b_offset_pips", 50)) * pip
        # tra l'entrata e lo stop: per un BUY sopra lo stop, per un SELL sotto
        limit_price = sl_a + off if buy else sl_a - off
        sl_b, tp = self._ml_levels("B", buy, limit_price, pip, tp1)
        res = self._send({
            "action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": b_lot,
            "type": mt5.ORDER_TYPE_BUY_LIMIT if buy else mt5.ORDER_TYPE_SELL_LIMIT,
            "price": round(limit_price, digits), "sl": round(sl_b, digits), "tp": round(tp, digits),
            "magic": self.magic, "comment": f"sfx{msg_id}-B", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        })
        b_ticket = res.order if self._ok(res) else None
        log.info("Segnale %s: 2) %s LIMIT %.2f lotti @ %s, SL %s, TP %s%s", msg_id, sig.side, b_lot,
                 round(limit_price, digits), round(sl_b, digits), tp1, "" if b_ticket is not None else " -> NON piazzato")

        self.state["signals"][str(msg_id)] = {
            "symbol": sym, "side": sig.side, "mode": "market_limit", "dry_run": self.dry_run,
            "tickets": [t for t in (a_ticket, b_ticket) if t is not None],
            "a_ticket": a_ticket, "b_ticket": b_ticket, "tp1": tp1, "levels_missing": not sig.complete,
            "opened_at": time.time(), "a_partial": False, "b_partial": False, "closed": False,
        }
        self.state["last_signal"] = msg_id
        self._save_state()

    def _ensure_sltp(self, p, sl: float, tp: float) -> None:
        info = mt5.symbol_info(p.symbol)
        tol = info.point / 2
        if abs((p.sl or 0) - sl) <= tol and abs((p.tp or 0) - tp) <= tol:
            return
        log.info("Posizione %s: correggo SL %s -> %s, TP %s -> %s", p.ticket, p.sl, round(sl, info.digits),
                 p.tp, round(tp, info.digits))
        self._send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": p.ticket,
                    "sl": round(sl, info.digits), "tp": round(tp, info.digits), "magic": self.magic})

    def _manage_market_limit(self, rec: dict) -> None:
        pos, orders = self._positions(rec)
        if not pos and not orders:
            rec["closed"] = True
            self._save_state()
            return
        info = mt5.symbol_info(rec["symbol"])
        pip = self.pip_size(info)
        tick = mt5.symbol_info_tick(rec["symbol"])
        tp1 = rec.get("tp1")
        a_alive = False
        for p in pos:
            leg = "A" if p.identifier == rec.get("a_ticket") else "B"
            a_alive |= leg == "A"
            buy = p.type == mt5.POSITION_TYPE_BUY
            done_key = "a_partial" if leg == "A" else "b_partial"
            if not rec.get(done_key):
                # prima della parziale: SL sempre a 100/50 pips dall'apertura reale, TP = TP1
                sl, tp = self._ml_levels(leg, buy, p.price_open, pip, tp1)
                self._ensure_sltp(p, sl, tp if tp1 else p.tp)
                pips = float(self.cfg.get("a_partial_pips", 30) if leg == "A" else self.cfg.get("b_partial_pips", 40))
                target = p.price_open + pips * pip if buy else p.price_open - pips * pip
                close_price = tick.bid if buy else tick.ask
                if (buy and close_price >= target) or (not buy and close_price <= target):
                    log.info("Operazione %s (%s): +%g pips dall'apertura %s -> chiudo il %s%% e pareggio",
                             leg, p.ticket, pips, p.price_open, self.cfg.get("partial_close_percent", 50))
                    self._partial_close(p)
                    rec[done_key] = True
                    self._save_state()
                    p = (mt5.positions_get(ticket=p.ticket) or [p])[0]
                    self._ensure_sltp(p, p.price_open, tp1 or p.tp)
            elif tp1 and abs((p.tp or 0) - tp1) > info.point / 2:
                # TP1 arrivato dopo (messaggio modificato): lo metto anche dopo la parziale
                self._ensure_sltp(p, p.sl, tp1)
        for o in orders:
            if not a_alive:
                # la prima operazione è chiusa (TP1, pareggio o chiusura): il limit non serve più
                log.info("Operazione 1 chiusa: cancello l'ordine limit %s", o.ticket)
                self._cancel_order(o)
            elif tp1 and abs((o.tp or 0) - tp1) > info.point / 2:
                log.info("Ordine limit %s: imposto TP %s", o.ticket, tp1)
                self._send({"action": mt5.TRADE_ACTION_MODIFY, "order": o.ticket, "price": o.price_open,
                            "sl": o.sl, "tp": round(tp1, info.digits), "type_time": o.type_time,
                            "expiration": o.time_expiration, "magic": self.magic})
