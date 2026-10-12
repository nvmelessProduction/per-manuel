"""Copia i segnali da un canale Telegram e li apre su MetaTrader 5.

Uso:
    python bot.py               # avvia il bot
    python bot.py --list        # elenca chat/canali con il loro ID (per trovare il canale giusto)
    python bot.py --config altro.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

from telethon import TelegramClient, events

from signal_parser import parse_signal, parse_update

log = logging.getLogger("bot")


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler("bot.log", encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)
    logging.getLogger("telethon").setLevel(logging.WARNING)


async def resolve_channel(client: TelegramClient, ref):
    """Accetta ID numerico, @username, link t.me o (parte del) nome del canale."""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.lstrip("-").isdigit()):
        return await client.get_entity(int(ref))
    try:
        return await client.get_entity(ref)
    except Exception:
        pass
    async for d in client.iter_dialogs():
        if ref.lower() in (d.name or "").lower():
            return d.entity
    raise SystemExit(f"Canale '{ref}' non trovato. Usa 'python bot.py --list' per vedere gli ID.")


async def list_dialogs(client: TelegramClient) -> None:
    async for d in client.iter_dialogs():
        kind = "canale" if d.is_channel else ("gruppo" if d.is_group else "chat")
        print(f"{d.id:>16}  {kind:7}  {d.name}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--list", action="store_true", help="elenca chat e canali con il loro ID")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    tg = cfg["telegram"]

    client = TelegramClient(tg.get("session_name", "seersfx"), int(tg["api_id"]), tg["api_hash"])
    await client.start()  # al primo avvio chiede numero di telefono e codice

    if args.list:
        await list_dialogs(client)
        return

    setup_logging()
    from mt5_trader import Trader  # import qui così --list funziona anche senza MT5

    trader = Trader(cfg.get("mt5", {}), cfg["trading"])
    trader.connect()
    if trader.dry_run:
        log.warning("MODALITÀ DRY RUN: nessun ordine reale verrà inviato (trading.dry_run = true)")

    channel = await resolve_channel(client, tg["channel"])
    log.info("In ascolto sul canale: %s (id %s)", getattr(channel, "title", channel), channel.id)
    max_age = int(cfg["trading"].get("max_signal_age_minutes", 15)) * 60

    def handle(msg, edited: bool) -> None:
        text = msg.message or ""
        if not text.strip():
            return
        log.info("%s messaggio %s:\n%s", "Modificato" if edited else "Nuovo", msg.id, text)

        sig = parse_signal(text)
        if sig:
            log.info("Segnale riconosciuto: %s", sig)
            if trader.has_signal(msg.id):
                if edited:
                    trader.update_levels(msg.id, sig)
                return
            # Un segnale vecchio modificato non va aperto in ritardo
            if time.time() - msg.date.timestamp() > max_age:
                log.warning("Segnale %s troppo vecchio, non lo apro", msg.id)
                return
            trader.open_signal(msg.id, sig)
            return

        upd = parse_update(text)
        if upd and not edited:
            trader.apply_update(upd, msg.reply_to_msg_id)
        elif not upd:
            log.info("Messaggio ignorato (né segnale né aggiornamento)")

    def safe(edited: bool):
        async def _h(event):
            try:
                await asyncio.to_thread(handle, event.message, edited)
            except Exception:
                log.exception("Errore gestendo il messaggio %s", event.message.id)
        return _h

    client.add_event_handler(safe(False), events.NewMessage(chats=channel))
    client.add_event_handler(safe(True), events.MessageEdited(chats=channel))

    try:
        await client.run_until_disconnected()
    finally:
        trader.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
