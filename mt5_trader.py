"""Esecuzione degli ordini su MetaTrader 5 (gira solo su Windows con il terminale MT5 installato)."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from types import SimpleNamespace

from signal_parser import Signal, Update

log = logging.getLogger("mt5")

try:
    import MetaTrader5 as mt5
except ImportError:  # permette di testare il parser anche fuori da Windows
    mt5 = None


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
        self._load_state()

    # ------------------------------------------------------------------ setup
    def connect(self) -> None:
        if mt5 is None:
            raise RuntimeError("Libreria MetaTrader5 non installata (pip install MetaTrader5, solo Windows).")
        kwargs = {}
        if self.mt5_cfg.get("path"):
            kwargs["path"] = self.mt5_cfg["path"]
        if self.mt5_cfg.get("login"):
            kwargs["login"] = int(self.mt5_cfg["login"])
            kwargs["password"] = self.mt5_cfg.get("password", "")
            kwargs["server"] = self.mt5_cfg.get("server", "")
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"mt5.initialize() fallito: {mt5.last_error()}")
        info = mt5.account_info()
        log.info("Connesso a MT5: conto %s (%s), saldo %.2f %s", info.login, info.server, info.balance, info.currency)
        if not mt5.terminal_info().trade_allowed:
            log.warning("ATTENZIONE: 'Algo Trading' è disattivato nel terminale MT5, gli ordini verranno rifiutati.")

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
        mapped = self.cfg.get("symbol_map", {}).get(symbol, symbol)
        return mapped + self.cfg.get("symbol_suffix", "")

    def _calc_lots(self, sym: str, info, order_type: int, entry: float, sl: float, legs: int) -> float:
        """Lotto per singola gamba (una gamba per ogni TP)."""
        step = info.volume_step
        if self.cfg.get("lot_mode", "fixed") == "risk":
            balance = mt5.account_info().balance
            risk_money = balance * float(self.cfg.get("risk_percent", 1.0)) / 100
            loss_per_lot = abs(mt5.order_calc_profit(order_type, sym, 1.0, entry, sl) or 0)
            if loss_per_lot <= 0:
                raise RuntimeError("Impossibile calcolare il rischio per lotto")
            per_leg = risk_money / loss_per_lot / legs
        else:
            per_leg = float(self.cfg.get("fixed_lot", 0.01))
        per_leg = min(per_leg, float(self.cfg.get("max_lot_per_leg", 1.0)), info.volume_max)
        per_leg = math.floor(per_leg / step + 1e-9) * step
        return round(max(per_leg, info.volume_min), 8)

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
            self._open_signal(msg_id, sig)

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
        if (buy and (price <= sig.sl or price >= sig.tps[0])) or (not buy and (price >= sig.sl or price <= sig.tps[0])):
            log.warning("Segnale %s scartato: prezzo attuale %s fuori dai livelli (SL %s, TP1 %s)",
                        msg_id, price, sig.sl, sig.tps[0])
            return

        in_zone = price <= sig.entry_high + tol if buy else price >= sig.entry_low - tol
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

        tps = sig.tps[: int(self.cfg.get("max_tps", len(sig.tps)))]
        lots = self._calc_lots(sym, info, order_type if action == mt5.TRADE_ACTION_DEAL else
                               (mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL), entry, sig.sl, len(tps))
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
                "sl": round(sig.sl, digits),
                "tp": round(tp, digits),
                "deviation": int(self.cfg.get("deviation_points", 50)),
                "magic": self.magic,
                "comment": f"sfx{msg_id}-TP{i}",
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
                log.info("  TP%d aperto, ticket %s", i, res.order)

        if tickets:
            self.state["signals"][str(msg_id)] = {
                "symbol": sym, "side": sig.side, "tickets": tickets, "entry": entry, "dry_run": self.dry_run}
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
            rec = self.state["signals"].get(str(msg_id))
            if not rec:
                return
            pos, orders = self._positions(rec)
            digits = mt5.symbol_info(rec["symbol"]).digits
            items = [(p, True) for p in pos] + [(o, False) for o in orders]
            for item, is_position in items:
                leg = rec["tickets"].index(item.identifier if is_position else item.ticket) + 1 \
                    if (item.identifier if is_position else item.ticket) in rec["tickets"] else 1
                tp = sig.tps[min(leg, len(sig.tps)) - 1]
                if is_position:
                    req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": item.symbol, "position": item.ticket}
                else:
                    req = {"action": mt5.TRADE_ACTION_MODIFY, "order": item.ticket, "price": item.price_open,
                           "type_time": item.type_time, "expiration": item.time_expiration}
                req.update({"sl": round(sig.sl, digits), "tp": round(tp, digits), "magic": self.magic})
                log.info("Segnale %s modificato: aggiorno ticket %s -> SL %s TP %s", msg_id, item.ticket, sig.sl, tp)
                self._send(req)

    def apply_update(self, upd: Update, reply_to: int | None) -> None:
        with self.lock:
            sig_id = str(reply_to) if reply_to and str(reply_to) in self.state["signals"] else (
                str(self.state["last_signal"]) if self.state["last_signal"] is not None else None)
            rec = self.state["signals"].get(sig_id) if sig_id else None
            if not rec:
                log.info("Aggiornamento ricevuto ma nessun segnale aperto a cui applicarlo")
                return
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
                    off = float(self.cfg.get("breakeven_offset_points", 0)) * mt5.symbol_info(p.symbol).point
                    buy = p.type == mt5.POSITION_TYPE_BUY
                    self._modify_sl(p, p.price_open + off if buy else p.price_open - off)
            elif upd.new_sl is not None:
                for p in pos:
                    self._modify_sl(p, upd.new_sl)
