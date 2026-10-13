"""Copia i segnali da un canale Telegram e li apre su MetaTrader 5.

Due modalità di lettura del canale (si sceglie in config.json -> telegram):
  - bot_token: un bot Telegram amministratore del canale (consigliato se il canale è tuo)
  - api_id/api_hash: il tuo account Telegram iscritto al canale

Uso:
    python bot.py               # avvia il programma
    python bot.py --list        # mostra gli ID dei canali (vedi README)
    python bot.py --config altro.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from signal_parser import parse_signal, parse_update

log = logging.getLogger("bot")


@dataclass
class Incoming:
    id: int
    text: str
    date: float  # timestamp unix
    reply_to: int | None
    edited: bool


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler("bot.log", encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)
    logging.getLogger("telethon").setLevel(logging.WARNING)


def make_handler(trader, max_age: int):
    def handle(msg: Incoming) -> None:
        if not msg.text.strip():
            return
        log.info("%s messaggio %s:\n%s", "Modificato" if msg.edited else "Nuovo", msg.id, msg.text)
        too_old = time.time() - msg.date > max_age

        sig = parse_signal(msg.text)
        if sig:
            log.info("Segnale riconosciuto: %s", sig)
            if trader.has_signal(msg.id):
                if msg.edited:
                    trader.update_levels(msg.id, sig)
                return
            # Un segnale vecchio (o modificato molto dopo) non va aperto in ritardo
            if too_old:
                log.warning("Segnale %s troppo vecchio, non lo apro", msg.id)
                return
            trader.open_signal(msg.id, sig)
            return

        upd = parse_update(msg.text)
        if not upd:
            log.info("Messaggio ignorato (né segnale né aggiornamento)")
        elif msg.edited or too_old:
            log.info("Aggiornamento modificato o vecchio, ignorato")
        else:
            trader.apply_update(upd, msg.reply_to)

    def safe(msg: Incoming) -> None:
        try:
            handle(msg)
        except Exception:
            log.exception("Errore gestendo il messaggio %s", msg.id)

    return safe


def start_trader(cfg: dict):
    from mt5_trader import Trader  # import qui così --list funziona anche senza MT5

    trader = Trader(cfg.get("mt5", {}), cfg["trading"])
    trader.connect()
    if trader.dry_run:
        log.warning("MODALITÀ DRY RUN: nessun ordine reale verrà inviato (trading.dry_run = true)")
    trader.start_manager()
    return trader


# ---------------------------------------------------------------- modalità BOT (Bot API)
def _ssl_context() -> ssl.SSLContext:
    # Su Windows Server appena installato spesso mancano i certificati radice che servono
    # per api.telegram.org: uso quelli di certifi, che sono sempre completi.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class BotApi:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.ssl = _ssl_context()

    def call(self, method: str, timeout: int = 70, **params):
        req = urllib.request.Request(self.base + method, data=json.dumps(params).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ssl) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:  # Telegram risponde con un errore (es. 401 token errato)
            data = json.load(e)
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data}")
        return data["result"]


def run_bot_mode(cfg: dict, list_only: bool) -> None:
    tg = cfg["telegram"]
    api = BotApi(tg["bot_token"])
    me = api.call("getMe")
    api.call("deleteWebhook")
    channel = tg.get("channel")
    channel = int(channel) if channel not in (None, "") and str(channel).lstrip("-").isdigit() else None

    if list_only:
        print(f"Bot @{me['username']} collegato. Scrivi un messaggio nel canale (il bot deve essere admin)...")
        print("Premi Ctrl+C per uscire.\n")
        offset = None
        while True:
            for u in api.call("getUpdates", offset=offset, timeout=50,
                              allowed_updates=["channel_post", "edited_channel_post", "message"]):
                offset = u["update_id"] + 1
                post = u.get("channel_post") or u.get("edited_channel_post") or u.get("message")
                if post:
                    chat = post["chat"]
                    print(f"{chat['id']:>16}  {chat.get('type'):8}  {chat.get('title') or chat.get('username')}")

    setup_logging()
    if channel is None:
        raise SystemExit("In modalità bot 'telegram.channel' deve essere l'ID numerico (es. -1001234567890). "
                         "Usa 'python bot.py --list' per trovarlo.")
    trader = start_trader(cfg)
    handle = make_handler(trader, int(cfg["trading"].get("max_signal_age_minutes", 15)) * 60)
    log.info("Bot @%s in ascolto sul canale %s", me["username"], channel)

    offset = None
    try:
        while True:
            try:
                updates = api.call("getUpdates", offset=offset, timeout=50,
                                   allowed_updates=["channel_post", "edited_channel_post"])
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                log.warning("Connessione a Telegram persa (%s), riprovo tra 5 secondi", e)
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                edited = "edited_channel_post" in u
                post = u.get("edited_channel_post") or u.get("channel_post")
                if not post or post["chat"]["id"] != channel:
                    continue
                handle(Incoming(
                    id=post["message_id"],
                    text=post.get("text") or post.get("caption") or "",
                    date=post["date"],
                    reply_to=(post.get("reply_to_message") or {}).get("message_id"),
                    edited=edited,
                ))
    finally:
        trader.shutdown()


# ---------------------------------------------------------------- modalità ACCOUNT (Telethon)
async def run_user_mode(cfg: dict, list_only: bool) -> None:
    from telethon import TelegramClient, events

    tg = cfg["telegram"]
    client = TelegramClient(tg.get("session_name", "seersfx"), int(tg["api_id"]), tg["api_hash"])
    await client.start()  # al primo avvio chiede numero di telefono e codice

    if list_only:
        async for d in client.iter_dialogs():
            kind = "canale" if d.is_channel else ("gruppo" if d.is_group else "chat")
            print(f"{d.id:>16}  {kind:7}  {d.name}")
        return

    setup_logging()
    trader = start_trader(cfg)
    handle = make_handler(trader, int(cfg["trading"].get("max_signal_age_minutes", 15)) * 60)

    ref = tg["channel"]
    channel = None
    if isinstance(ref, int) or str(ref).lstrip("-").isdigit():
        channel = await client.get_entity(int(ref))
    else:
        try:
            channel = await client.get_entity(ref)
        except Exception:
            async for d in client.iter_dialogs():
                if ref.lower() in (d.name or "").lower():
                    channel = d.entity
                    break
    if channel is None:
        raise SystemExit(f"Canale '{ref}' non trovato. Usa 'python bot.py --list' per vedere gli ID.")
    log.info("In ascolto sul canale: %s (id %s)", getattr(channel, "title", channel), channel.id)

    def on_event(edited: bool):
        async def _h(event):
            m = event.message
            await asyncio.to_thread(handle, Incoming(m.id, m.message or "", m.date.timestamp(),
                                                     m.reply_to_msg_id, edited))
        return _h

    client.add_event_handler(on_event(False), events.NewMessage(chats=channel))
    client.add_event_handler(on_event(True), events.MessageEdited(chats=channel))
    try:
        await client.run_until_disconnected()
    finally:
        trader.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--list", action="store_true", help="mostra gli ID dei canali")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    try:
        if cfg["telegram"].get("bot_token"):
            run_bot_mode(cfg, args.list)
        else:
            asyncio.run(run_user_mode(cfg, args.list))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
