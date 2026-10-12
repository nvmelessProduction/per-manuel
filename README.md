# Telegram → MetaTrader 5 signal copier

Legge i segnali dal canale Telegram (es. SEERS.FX) e li apre automaticamente su MetaTrader 5.

## Cosa fa

| Messaggio sul canale | Azione su MT5 |
|---|---|
| `VENDI/COMPRA ORO (XAUUSD)` + zona d'ingresso + SL + TP1/TP2 | Apre **una posizione per ogni TP** (stesso SL). Se il prezzo è già in zona → ordine a mercato, altrimenti ordine limit sul bordo della zona |
| Segnale **modificato** dopo l'invio | Aggiorna SL/TP delle posizioni già aperte |
| "metti in sicurezza parte dei profitti" / "parziale" | Chiude la posizione del TP1 (o il `partial_close_percent` se ce n'è solo una) |
| "porta lo stop a pareggio" / "BE" / "break even" | Sposta lo SL al prezzo d'ingresso (+ `breakeven_offset_points`) |
| "sposta lo stop a 4165" | Sposta lo SL a 4165 |
| "chiudi" / "chiudiamo" / "close" | Chiude tutto e cancella i pendenti |

Gli aggiornamenti vengono applicati al segnale a cui il messaggio **risponde** (reply); se non è una risposta, all'ultimo segnale aperto.

## Installazione sulla VPS Windows

1. Installa **Python 3.11+** da python.org (spunta "Add Python to PATH").
2. Installa e apri **MetaTrader 5**, fai login sul conto e attiva il pulsante **Algo Trading**.
3. Nella cartella del progetto:
   ```
   pip install -r requirements.txt
   ```
4. Vai su <https://my.telegram.org> → *API development tools* → crea un'app e copia `api_id` e `api_hash`.
5. Copia `config.example.json` in `config.json` e compila:
   - `telegram.api_id`, `telegram.api_hash`
   - `telegram.channel`: ID numerico, `@username`, oppure parte del nome del canale
6. Primo avvio (chiede numero di telefono e codice Telegram, poi resta salvato nel file `.session`):
   ```
   python bot.py --list
   ```
   Mostra tutti i canali con il loro ID: copia l'ID del canale dei segnali in `telegram.channel`.
7. Avvia:
   ```
   python bot.py
   ```

Il programma usa **il tuo account Telegram** (non un bot), quindi legge qualsiasi canale a cui sei iscritto.

## Configurazione (`config.json` → `trading`)

| Chiave | Significato |
|---|---|
| `dry_run` | `true` = scrive nel log cosa farebbe ma **non invia ordini**. Lascialo `true` finché non hai verificato che funziona, poi metti `false` |
| `lot_mode` | `"risk"` (lotto calcolato sul rischio) oppure `"fixed"` |
| `risk_percent` | % del saldo rischiata sull'intero segnale (divisa tra le gambe TP1/TP2) |
| `fixed_lot` | lotto per ogni gamba se `lot_mode = "fixed"` |
| `max_lot_per_leg` | limite massimo di sicurezza per ogni posizione |
| `max_tps` | quanti TP usare (es. `1` = una sola posizione sul TP1) |
| `symbol_map` / `symbol_suffix` | se il broker chiama l'oro diversamente: es. `{"XAUUSD": "GOLD"}` o suffisso `".m"` |
| `entry_tolerance_points` | quanto fuori dalla zona si accetta ancora l'ingresso a mercato (oro: 200 punti = 2$) |
| `use_pending_orders` | se il prezzo non è in zona mette un ordine limit; se `false` ignora il segnale |
| `pending_expiry_minutes` | scadenza dell'ordine limit (0 = mai) |
| `breakeven_offset_points` | il "+" del BE+ (oro: 50 punti = 0,50$ di profitto) |
| `partial_close_percent` | % da chiudere nel parziale quando c'è una sola posizione |
| `max_signal_age_minutes` | non apre segnali più vecchi di così (es. dopo un riavvio) |

In `mt5` puoi lasciare tutto vuoto se il terminale è già aperto e loggato; altrimenti indica `path` del `terminal64.exe`, `login`, `password`, `server`.

## File generati

- `bot.log`: log completo di messaggi ricevuti e ordini
- `state.json`: collegamento tra messaggi e ticket MT5 (non cancellarlo con posizioni aperte)
- `*.session`: login Telegram (**non condividerlo**: dà accesso al tuo account)

## Test del parser

```
python -m unittest discover -s tests
```

> ⚠️ Il trading automatico comporta rischi: prova prima su un conto **demo** e con `dry_run: true`.
