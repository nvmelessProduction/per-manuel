# Guida all'installazione sulla VPS Windows

Tempo richiesto: circa 30 minuti. Serve:
- una VPS Windows (Windows Server 2019/2022 o Windows 10/11)
- il conto del broker (meglio **demo** per le prove)
- essere amministratore del canale Telegram dei segnali

---

## 1. Collegarsi alla VPS

1. Dal PC: apri **Connessione Desktop remoto** (cerca "mstsc" nel menu Start). Dal Mac usa l'app *Windows App* (ex Microsoft Remote Desktop).
2. Inserisci IP, utente e password che ti ha dato il fornitore della VPS.
3. Quando hai finito, **chiudi la finestra con la X** e **non fare "Disconnetti / Esci"** da Windows: così i programmi restano accesi.

## 2. Installare MetaTrader 5

1. Sulla VPS scarica MT5 **dal sito del tuo broker** (così ha già i server giusti), oppure da metatrader5.com.
2. Installalo e fai login: *File → Accedi al conto di trading*, con numero conto, password e server.
3. Attiva il trading automatico:
   - *Strumenti → Opzioni → Expert Advisors* → spunta **"Consenti trading algoritmico"** → OK
   - nella barra in alto il pulsante **Algo Trading** deve essere **verde**
4. Controlla il nome dell'oro dal tuo broker: *Visualizza → Market Watch* (Ctrl+M), tasto destro → *Simboli*, cerca "XAU" o "GOLD".
   Segnati il nome esatto (es. `XAUUSD`, `XAUUSD.m`, `GOLD`, `XAUUSD+`): servirà al punto 7.
5. **Lascia MT5 sempre aperto e loggato.**

## 3. Installare Python

1. Vai su <https://www.python.org/downloads/windows/> e scarica **Python 3.12** → *Windows installer (64-bit)*.
   (Deve essere a 64 bit, come MT5.)
2. Nella prima schermata dell'installazione spunta **"Add python.exe to PATH"** → *Install Now*.
3. Verifica: apri il **Prompt dei comandi** (Start → scrivi `cmd`) e digita:
   ```
   python --version
   ```
   Deve rispondere `Python 3.12.x`.

## 4. Scaricare il programma

1. Sulla VPS apri il browser e vai su <https://github.com/nvmelessproduction/per-manuel> (fai login su GitHub se il repository è privato).
2. In alto a sinistra cambia il branch da `main` a **`telegram-mt5-copier`**.
3. Pulsante verde **Code → Download ZIP**.
4. Estrai lo ZIP in una cartella semplice, ad esempio `C:\copier`
   (dentro devono esserci direttamente `bot.py`, `config.example.json`, `avvia.bat`, …).

## 5. Installare le librerie

Nel Prompt dei comandi:
```
cd C:\copier
pip install -r requirements.txt
```
Deve finire con *Successfully installed … telethon … MetaTrader5 …*.

## 6. Creare il bot Telegram e renderlo amministratore del canale

Il programma legge il canale tramite un **bot** che è amministratore del canale (serve essere proprietari del canale).

1. In Telegram cerca **@BotFather** (con la spunta blu) e premi *Avvia*.
2. Scrivi `/newbot`:
   - nome: ad esempio `SeersFX Copier`
   - username: deve finire con `bot`, ad esempio `seersfx_copier_bot`
3. BotFather risponde con il **token**, una stringa tipo `7123456789:AAH...`. Copialo.
   **Non darlo a nessuno**: chi lo ha può leggere il canale tramite il bot.
4. Apri il canale → nome del canale in alto → **Amministratori → Aggiungi amministratore** → cerca lo username del bot → aggiungilo.
   Puoi **togliere tutti i permessi** (pubblicare, modificare, ecc.): al bot serve solo essere admin per ricevere i messaggi.

## 7. Configurare il programma

Nel Prompt dei comandi:
```
cd C:\copier
copy config.example.json config.json
notepad config.json
```
Modifica e salva (Ctrl+S):

```
"telegram": {
  "bot_token": "7123456789:AAH...",        <- il token di BotFather (tra virgolette)
  "channel": -1001234567890,               <- l'ID del canale (punto 8), numero senza virgolette
  ...                                      <- il resto lascialo com'è
},
```

Nella sezione `trading`:
- `"dry_run": true` → per ora **lascialo true** (prova senza ordini veri)
- `"symbol_map": { "XAUUSD": "NOME_DEL_TUO_BROKER" }` → il nome visto al punto 2.4 (es. `"GOLD"`).
  Se il broker aggiunge solo un suffisso puoi usare `"symbol_suffix": ".m"`.
- `"max_tps": 1` se il conto è piccolo (apre una sola posizione invece di due)

La sezione `mt5` lasciala così se MT5 è già aperto e loggato.
Se preferisci che il programma faccia il login da solo:
```json
"mt5": {
  "path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
  "login": 12345678,
  "password": "la_tua_password",
  "server": "NomeBroker-Server"
}
```
(nel percorso servono le **doppie barre** `\\`).

> Attenzione alle virgole e alle virgolette: se il JSON è sbagliato il programma si ferma con un errore che indica la riga.

## 8. Trovare l'ID del canale

**Modo 1 (il più semplice):** apri il canale su <https://web.telegram.org> dal computer.
L'indirizzo finisce con l'ID, ad esempio `web.telegram.org/a/#-1001234567890`.
Copia il numero **con il segno meno** in `"channel"`.

**Modo 2:** con il token già inserito nel config:
```
cd C:\copier
python bot.py --list
```
Poi pubblica un messaggio qualsiasi nel canale (puoi cancellarlo subito dopo): nella finestra compare
```
  -1001234567890  channel   SEERS.FX-⚠️📊
```
Copia l'ID in `config.json` e chiudi con Ctrl+C.

## 9. Prova in modalità dry run

Fai doppio clic su **`avvia.bat`** (oppure `python bot.py` dal Prompt). Nella finestra devi vedere:
```
Connesso a MT5: conto 12345678 (NomeBroker-Server), saldo ...
MODALITÀ DRY RUN: nessun ordine reale verrà inviato
Bot @seersfx_copier_bot in ascolto sul canale -1001234567890
```
Quando arriva un segnale vedrai `Segnale riconosciuto` e le righe `[DRY RUN] order_send …` con lotto, SL e TP che avrebbe usato.

**Per provare subito senza disturbare gli iscritti:**
1. Crea un canale privato di prova e aggiungi lo stesso bot come amministratore.
2. Metti l'ID del canale di prova in `channel` (punto 8) e avvia.
3. Pubblica un segnale nello stesso formato con **livelli vicini al prezzo attuale** (altrimenti viene scartato perché il prezzo è già oltre SL/TP).
4. Rispondi a quel messaggio con un aggiornamento ("porta lo stop a pareggio") per provare la gestione.
5. Finite le prove, rimetti l'ID del canale vero.

## 10. Passare agli ordini veri

1. Chiudi il programma (chiudi la finestra).
2. In `config.json` metti `"dry_run": false`.
3. Riavvia con `avvia.bat`, **prima su conto demo** per qualche giorno, poi su quello reale.
4. Le posizioni aperte dal programma hanno commento `sfx<numero>-TP1`, `sfx<numero>-TP2` e magic number `260412`.

## 11. Tenerlo acceso 24/7

- Lascia aperti **MT5** e la finestra di **avvia.bat**, poi chiudi il Desktop remoto con la X.
- Se il programma si chiude per un errore, `avvia.bat` lo riavvia da solo dopo 15 secondi.
- Avvio automatico: premi `Win+R`, scrivi `shell:startup`, Invio, e mettici un **collegamento** ad `avvia.bat` (e uno a MT5).
  Nota: parte quando entri in Windows; dopo un riavvio della VPS collegati una volta col Desktop remoto.
- Consigliato: disattiva i riavvii automatici di Windows Update, o controlla la VPS dopo gli aggiornamenti.

## 12. Aggiornare il programma

Scarica il nuovo ZIP ed estrailo sopra la cartella, **mantenendo** questi file:
`config.json` e `state.json`.

---

## Problemi comuni

| Messaggio | Soluzione |
|---|---|
| `'python' non è riconosciuto…` | Python installato senza "Add to PATH": reinstallalo spuntando l'opzione |
| `mt5.initialize() fallito` | MT5 non aperto/loggato, oppure Python a 32 bit. Prova a indicare `path`, `login`, `password`, `server` in `config.json` |
| `Algo Trading è disattivato` / retcode `10027` | Attiva il pulsante **Algo Trading** in MT5 (punto 2.3) |
| `Simbolo XAUUSD non trovato sul broker` | Imposta `symbol_map` o `symbol_suffix` (punto 7) |
| Il bot non riceve i messaggi | Il bot deve essere **amministratore** del canale e `channel` deve essere l'ID con il `-100` davanti |
| `Telegram getMe: ... Unauthorized` | Token del bot sbagliato: ricopialo da @BotFather |
| `Segnale scartato: prezzo attuale fuori dai livelli` | Normale: il prezzo era già oltre lo SL o il TP1 quando è arrivato il segnale |
| retcode `10019` | Margine insufficiente per il lotto |
| retcode `10018` | Mercato chiuso |
| retcode `10016` | Stop troppo vicini al prezzo per le regole del broker |
| `Expecting ',' delimiter` / errore JSON | Errore di sintassi in `config.json` (virgola o virgolette mancanti) |

Tutto quello che succede viene scritto anche in **`bot.log`** nella cartella del programma: in caso di problemi manda quel file.

---

## Alternativa: leggere il canale con un account Telegram (se non sei admin)

Se non puoi aggiungere un bot al canale, il programma può leggere con un account iscritto:
1. Su <https://my.telegram.org> → *API development tools* crea un'app e copia **api_id** e **api_hash**.
2. In `config.json` lascia `"bot_token": ""` e compila `"api_id"` (numero) e `"api_hash"`.
3. Lancia `python bot.py --list`: chiede numero di telefono, codice (arriva nell'app Telegram) ed eventuale password, poi mostra gli ID dei canali.
4. Il login resta nel file `seersfx.session`: **non condividerlo**, dà accesso all'account.
