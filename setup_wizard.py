"""Configurazione guidata: chiede i dati, li verifica e scrive config.json.

Viene lanciato da INSTALLA.bat / CONFIGURA.bat, ma si può avviare anche a mano:
    python setup_wizard.py --terminal "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error

from bot import BotApi

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")


# ---------------------------------------------------------------- input
def title(t: str) -> None:
    print("\n" + "=" * 64 + f"\n  {t}\n" + "=" * 64)


def ask(prompt: str, default=None, secret: bool = False) -> str:
    if default in (None, ""):
        hint = ""
    else:
        hint = " [INVIO = quella salvata]" if secret else f" [{default}]"
    while True:
        v = (getpass.getpass(f"{prompt}{hint}: ") if secret else input(f"{prompt}{hint}: ")).strip()
        if v:
            return v
        if default not in (None, ""):
            return str(default)
        print("  -> campo obbligatorio")


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "S/n" if default else "s/N"
    while True:
        v = input(f"{prompt} ({d}): ").strip().lower()
        if not v:
            return default
        if v in ("s", "si", "sì", "y", "yes"):
            return True
        if v in ("n", "no"):
            return False


def ask_choice(prompt: str, options: list[str], default: int = 1) -> int:
    print(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}) {o}")
    while True:
        v = input(f"Scelta [{default}]: ").strip() or str(default)
        if v.isdigit() and 1 <= int(v) <= len(options):
            return int(v)


def ask_number(prompt: str, default: float, lo: float, hi: float) -> float:
    while True:
        v = input(f"{prompt} [{default}]: ").strip().replace(",", ".") or str(default)
        try:
            n = float(v)
            if lo <= n <= hi:
                return n
        except ValueError:
            pass
        print(f"  -> inserisci un numero tra {lo} e {hi}")


def pause(msg: str = "Premi INVIO per continuare...") -> None:
    input(msg)


# ---------------------------------------------------------------- Telegram
def setup_telegram(old: dict) -> dict:
    title("1/4  TELEGRAM")
    print("Serve il bot creato con @BotFather (comando /newbot), che deve essere")
    print("AMMINISTRATORE del canale dei segnali.\n")
    while True:
        raw = ask("Incolla il token del bot", old.get("bot_token") or None)
        # accetta anche testo in più copiato da BotFather (es. "HTTP API: 123:ABC...")
        m = re.search(r"\d{6,}:[A-Za-z0-9_-]{30,}", raw)
        if not m:
            print("  -> Questo non sembra un token (formato: 1234567890:AAH...). Ricopialo da @BotFather.")
            continue
        token = m.group(0)
        api = BotApi(token)
        try:
            me = api.call("getMe", timeout=20)
            break
        except RuntimeError as e:
            if "401" in str(e) or "Unauthorized" in str(e):
                print("  -> Telegram dice che il token non è valido. Ricopialo da @BotFather.")
            else:
                print(f"  -> Errore da Telegram: {e}")
        except Exception as e:
            print(f"  -> Non riesco a collegarmi a Telegram: {type(e).__name__}: {e}")
            if "CERTIFICATE" in str(e).upper():
                print("     (problema di certificati SSL: chiudi e rilancia l'installazione, che li aggiorna)")
            else:
                print("     Controlla che la VPS abbia internet e che un antivirus/firewall non blocchi Python.")
        old = {}
    print(f"  OK, bot: @{me['username']}")
    api.call("deleteWebhook", timeout=20)

    channel = old.get("channel")
    if channel and ask_yes(f"Uso il canale già configurato ({channel})?"):
        return {"bot_token": token, "channel": int(channel)}

    print(f"\n1. Aggiungi @{me['username']} come AMMINISTRATORE del canale")
    print("   (canale -> Amministratori -> Aggiungi amministratore; puoi togliergli tutti i permessi).")
    print("2. Poi PUBBLICA UN MESSAGGIO QUALSIASI nel canale (es. 'test'); dopo puoi cancellarlo.\n")
    print("Aspetto il messaggio (massimo 10 minuti)...")

    offset = None
    # scarta i messaggi vecchi
    for u in api.call("getUpdates", timeout=20, offset=-1, allowed_updates=["channel_post"]):
        offset = u["update_id"] + 1
    deadline = time.time() + 600
    while time.time() < deadline:
        try:
            updates = api.call("getUpdates", timeout=40, offset=offset, allowed_updates=["channel_post"])
        except (urllib.error.URLError, OSError):
            time.sleep(3)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            chat = (u.get("channel_post") or {}).get("chat")
            if not chat:
                continue
            name = chat.get("title") or chat.get("username")
            if ask_yes(f"\nRicevuto un messaggio dal canale '{name}' (ID {chat['id']}). È quello giusto?"):
                return {"bot_token": token, "channel": chat["id"]}
            print("Ok, pubblica un messaggio nel canale giusto...")
    print("Nessun messaggio ricevuto. Controlla che il bot sia amministratore del canale.")
    channel = ask("Inserisci a mano l'ID del canale (es. -1001234567890)")
    return {"bot_token": token, "channel": int(channel)}


# ---------------------------------------------------------------- MetaTrader 5
def kill_terminal(path: str) -> None:
    ps = f"Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq '{path}' }} | Stop-Process -Force"
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    time.sleep(3)


def start_terminal_with_login(path: str, login: int, password: str, server: str) -> None:
    """Avvia MT5 con login automatico e Algo Trading attivo (file di avvio /config)."""
    ini = os.path.join(HERE, "mt5_avvio.ini")
    with open(ini, "w", encoding="utf-16") as f:
        f.write("[Common]\n"
                f"Login={login}\nPassword={password}\nServer={server}\n"
                "KeepPrivate=1\nNewsEnable=0\n"
                "[Experts]\nAllowLiveTrading=1\nAllowDllImport=0\nEnabled=1\nAccount=0\nProfile=0\n")
    kill_terminal(path)
    subprocess.Popen([path, "/portable", f"/config:{ini}"])
    time.sleep(25)
    try:
        os.remove(ini)  # contiene la password
    except OSError:
        pass


def setup_mt5(old: dict, terminal: str | None):
    import MetaTrader5 as mt5

    title("2/4  METATRADER 5")
    path = terminal or old.get("path")
    while not path or not os.path.exists(path):
        path = ask("Percorso di terminal64.exe (es. C:\\Program Files\\MetaTrader 5\\terminal64.exe)")
    print(f"Terminale: {path}\n")
    print("Inserisci i dati del conto di trading (li trovi nella mail del broker).")

    while True:
        login = int(ask("Numero del conto (login)", old.get("login")))
        password = ask("Password del conto (mentre scrivi non si vede nulla, è normale)", old.get("password"), secret=True)
        server = ask("Server (es. ICMarketsSC-Demo)", old.get("server"))
        print("\nAvvio MetaTrader 5 e faccio il login, attendi circa 30 secondi...")
        start_terminal_with_login(path, login, password, server)
        ok = mt5.initialize(path=path, login=login, password=password, server=server, timeout=120000, portable=True)
        if ok and mt5.account_info() is not None:
            break
        print(f"\n  -> Login non riuscito: {mt5.last_error()}")
        mt5.shutdown()
        print("     Controlla numero conto, password e nome del server (deve essere identico a quello del broker).")
        print("     Se il server non viene trovato: in MetaTrader 5 apri File -> Apri un conto, cerca il nome")
        print("     del broker e chiudi la finestra; poi riprova qui.")
        pause("Premi INVIO per riprovare...")
        old = {"login": login, "server": server}

    info = mt5.account_info()
    print(f"  OK, collegato al conto {info.login} ({info.server}) - saldo {info.balance:.2f} {info.currency}")

    while not mt5.terminal_info().trade_allowed:
        print("\n  -> In MetaTrader 5 il pulsante 'Algo Trading' (in alto) è spento.")
        print("     Cliccalo finché diventa VERDE.")
        pause("Fatto? Premi INVIO...")

    hedging = info.margin_mode == 2  # ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
    if not hedging:
        print("\n  ATTENZIONE: il conto è di tipo NETTING (non hedging): userò una sola posizione per segnale.")

    return mt5, {"path": path, "portable": True, "login": login, "password": password, "server": server}, hedging


def setup_trading(mt5, old: dict, hedging: bool) -> dict:
    from mt5_trader import find_broker_symbol

    title("3/4  STRUMENTO")
    gold = find_broker_symbol("XAUUSD")
    if gold and ask_yes(f"Il tuo broker chiama l'oro '{gold}'. Corretto?"):
        pass
    else:
        gold = ask("Scrivi il nome esatto dell'oro come appare in MetaTrader (es. XAUUSD, GOLD, XAUUSD.m)")
    mt5.symbol_select(gold, True)
    sym = mt5.symbol_info(gold)
    tick = mt5.symbol_info_tick(gold)

    title("4/4  RISCHIO E MODALITÀ")
    options = [
        "1 posizione a mercato: dopo X pips di profitto chiude una parte (es. 50%) e porta lo stop al PREZZO DI ENTRATA",
        "1 posizione a mercato: dopo X pips di profitto chiude una parte (es. 50%) e avvia un TRAILING STOP",
    ]
    if hedging:
        options.append("2 posizioni separate: una chiude al TP1, l'altra al TP2")
    old_mode = {"tp1_be": 1, "tp1_trailing": 2, "two_positions": 3}.get(old.get("management"), 1)
    choice = ask_choice("Come gestire ogni segnale?", options, old_mode if old_mode <= len(options) else 1)
    management = {1: "tp1_be", 2: "tp1_trailing", 3: "two_positions"}[choice]
    extra = {"management": management}
    tps = 2 if management == "two_positions" else 1
    if management != "two_positions":
        print("  (sull'oro 1 pip = 0,10$: 40 pips = 4$)")
        extra["partial_trigger"] = "pips"
        extra["partial_pips"] = ask_number("Dopo quanti pips di profitto dall'apertura chiudere una parte", old.get("partial_pips", 40), 1, 10000)
        extra["partial_close_percent"] = ask_number("Percentuale da chiudere", old.get("partial_close_percent", 50), 1, 99)
        print("  (per poter chiudere una parte, il lotto minimo aperto sarà 0,02)")
        # il resto della posizione va esattamente al prezzo di entrata; i messaggi del canale
        # tipo "siamo in profitto, metti BE" vengono ignorati (vale solo "chiudi")
        extra.update({"breakeven_offset_pips": 0, "entry_mode": "market", "use_pending_orders": False,
                      "channel_updates": "close_only"})
    if management == "tp1_trailing":
        print("  Nota: sull'oro 1 pip = 0,10$  ->  3 pips = 0,30$ (molto stretto, circa lo spread).")
        extra["trailing_pips"] = ask_number("Distanza del trailing stop in pips", old.get("trailing_pips", 3), 0.5, 1000)

    balance = mt5.account_info().balance
    if sym and tick and tick.bid:
        loss = abs(mt5.order_calc_profit(mt5.ORDER_TYPE_SELL, gold, sym.volume_min, tick.bid, tick.bid + 8) or 0)
        if loss:
            print(f"\nEsempio: con uno stop loss di 8$ (come nei segnali del canale) il minimo che il bot apre "
                  f"({2 * sym.volume_min:g} lotti in totale) rischia circa {2 * loss:.2f} = "
                  f"{2 * loss / balance * 100:.1f}% del conto.")

    mode = ask_choice("\nCome calcolo il lotto?",
                      ["Percentuale del conto (consigliato)", "Lotto fisso"], 1)
    trading = {}
    if mode == 1:
        trading["lot_mode"] = "risk"
        trading["risk_percent"] = ask_number("Percentuale del conto da rischiare per segnale", old.get("risk_percent", 1.0), 0.1, 10)
        print("  (se il conto è troppo piccolo per quella percentuale, verrà aperto il lotto minimo)")
    else:
        trading["lot_mode"] = "fixed"
        trading["fixed_lot"] = ask_number("Lotto per ogni posizione", old.get("fixed_lot", 0.01), 0.01, 100)
    trading["max_lot_per_leg"] = ask_number("Lotto massimo di sicurezza per posizione", old.get("max_lot_per_leg", 1.0), 0.01, 100)

    real = ask_choice("\nModalità di funzionamento:",
                      ["PROVA - legge i segnali e scrive nel log cosa farebbe, NON apre ordini (consigliato i primi giorni)",
                       "REALE - apre davvero gli ordini"], 1)
    if real == 2 and not ask_yes("Confermi la modalità REALE?", False):
        real = 1

    trading.update(extra)
    trading.update({
        "dry_run": real == 1,
        "max_tps": tps,
        "symbol_map": {"XAUUSD": gold},
        "symbol_suffix": "",
    })
    return trading


# ---------------------------------------------------------------- main
DEFAULT_TRADING = {
    "dry_run": True, "magic": 260412,
    "lot_mode": "risk", "risk_percent": 1.0, "fixed_lot": 0.01, "max_lot_per_leg": 1.0, "max_tps": 2,
    "symbol_map": {}, "symbol_suffix": "",
    "entry_tolerance_points": 200, "use_pending_orders": False, "pending_expiry_minutes": 120,
    "deviation_points": 50, "breakeven_offset_points": 50, "partial_close_percent": 50,
    "management": "tp1_be", "trailing_pips": 3, "trailing_step_pips": 1, "pip_size": None,
    "partial_trigger": "pips", "partial_pips": 40, "breakeven_offset_pips": 0, "entry_mode": "market",
    "channel_updates": "close_only", "merge_levels_minutes": 15,
    "max_signal_age_minutes": 15,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terminal", help="percorso di terminal64.exe")
    args = ap.parse_args()

    old = {}
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            old = json.load(f)

    print("\nCONFIGURAZIONE DEL COPIATORE DI SEGNALI TELEGRAM -> METATRADER 5")
    print("Rispondi alle domande. Tra parentesi quadre c'è il valore proposto: premi INVIO per accettarlo.")

    telegram = setup_telegram(old.get("telegram", {}))
    mt5, mt5_cfg, hedging = setup_mt5(old.get("mt5", {}), args.terminal)
    trading = dict(DEFAULT_TRADING, **old.get("trading", {}))
    trading.update(setup_trading(mt5, old.get("trading", {}), hedging))
    mt5.shutdown()  # il terminale resta aperto e loggato

    cfg = {"telegram": telegram, "mt5": mt5_cfg, "trading": trading}
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    title("CONFIGURAZIONE COMPLETATA")
    print(f"  Canale:     {telegram['channel']}")
    print(f"  Conto MT5:  {mt5_cfg['login']} ({mt5_cfg['server']})")
    print(f"  Oro:        {trading['symbol_map']['XAUUSD']}")
    print(f"  Lotto:      " + (f"{trading['risk_percent']}% del conto" if trading["lot_mode"] == "risk"
                                else f"fisso {trading['fixed_lot']}"))
    at = f"a +{trading.get('partial_pips', 40):g} pips chiude il {trading.get('partial_close_percent', 50):g}%"
    print("  Gestione:   " + {
        "tp1_be": f"1 posizione a mercato, {at} e stop al prezzo di entrata",
        "tp1_trailing": f"1 posizione a mercato, {at} e trailing stop di {trading.get('trailing_pips', 3):g} pips",
        "two_positions": "2 posizioni (TP1 e TP2)",
    }[trading.get("management", "two_positions")])
    print(f"  Modalità:   {'PROVA (nessun ordine reale)' if trading['dry_run'] else 'REALE'}")
    print("\nPer cambiare questi dati in futuro: doppio clic su CONFIGURA.bat")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nConfigurazione annullata.")
        sys.exit(1)
