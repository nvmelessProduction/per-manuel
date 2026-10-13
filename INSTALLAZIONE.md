# Guida all'installazione (automatica)

Questa guida porta da **VPS appena comprata** a **copiatore attivo che apre i trade da solo**.
L'installazione vera è **un doppio clic**. Le uniche cose da fare a mano sono quelle che solo tu puoi fare:
creare il bot su Telegram e scrivere i tuoi dati quando il programma te li chiede.

Tempo totale: **circa 20-30 minuti**.

---

## Prima di iniziare: cosa ti serve

Tienili a portata di mano, il programma te li chiederà:

| Cosa | Dove lo trovi |
|---|---|
| **IP, utente e password della VPS** | Mail del fornitore della VPS |
| **Token del bot Telegram** | Lo crei al passo 2 (2 minuti) |
| **Numero conto, password e server del conto MT5** | Mail del broker quando hai aperto il conto (meglio un conto **DEMO** per iniziare) |
| *(facoltativo)* **Link di download di MetaTrader 5 del tuo broker** | Sito del broker, sezione "Piattaforme" / "Scarica MT5" |
| **Il telefono** con Telegram, per creare il bot e aggiungerlo al canale | — |

> **Che VPS prendere:** Windows Server 2022 (o 2019), **almeno 2 GB di RAM e 40 GB di disco**.
> Quella da 1 GB / 25 GB è troppo piccola: Windows da solo la riempie.

---

## Passo 1 – Collegarsi alla VPS

**Da PC Windows**
1. Premi il tasto **Windows**, scrivi `Connessione Desktop remoto` e aprila.
2. In *Computer* scrivi l'**IP** della VPS → **Connetti**.
3. Inserisci **utente** (di solito `Administrator`) e **password** → OK.
4. Se compare un avviso sul certificato → **Sì**.

**Da Mac**
1. Installa dall'App Store **Windows App** (prima si chiamava *Microsoft Remote Desktop*).
2. **+** → *Aggiungi PC* → scrivi l'IP → salva → doppio clic sul PC → utente e password.

**Da iPhone / Android**: stessa app *Windows App* (o *Remote Desktop*), stessi passaggi. Funziona, ma da computer è molto più comodo.

Vedrai il desktop di Windows Server. Se si apre la finestra **Server Manager**, chiudila.

> ❗ Quando avrai finito, per uscire **chiudi la finestra del Desktop remoto con la X**.
> **Non** fare *Start → Disconnetti/Esci*: chiuderebbe anche i programmi.

---

## Passo 2 – Creare il bot Telegram (dal telefono)

1. Su Telegram cerca **@BotFather** (con la spunta blu) → **Avvia**.
2. Scrivi `/newbot`.
3. Ti chiede il **nome**: scrivi ad esempio `SeersFX Copier`.
4. Ti chiede lo **username**: deve finire con `bot`, ad esempio `seersfxbot` (se è già preso provane un altro).
5. BotFather risponde con un messaggio che contiene il **token**, tipo:
   ```
   7123456789:AAHk3j2...
   ```
   Tienilo: lo incollerai al passo 4. **Non darlo a nessuno.**

*Non serve ancora aggiungerlo al canale: te lo dirà il programma al momento giusto.*

---

## Passo 3 – Il comando unico

Tutto **dentro la VPS** (nel Desktop remoto):

1. Copia questo comando (sul tuo PC/telefono, poi lo incolli nella VPS):
   ```
   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/nvmelessproduction/per-manuel/telegram-mt5-copier/get.ps1 | iex"
   ```
   > Il Desktop remoto condivide gli appunti: copi sul tuo PC e incolli nella VPS.
   > Se non funziona, apri questa guida su github.com **dal browser della VPS** e copia il comando da lì.
2. Nella VPS premi **Windows + R** (si apre la finestra *Esegui*).
3. Incolla il comando (**Ctrl + V**) e premi **INVIO**.
4. Se compare **"Vuoi consentire a questa app di apportare modifiche?"** → **Sì**.

<details>
<summary>In alternativa, senza comando (scaricando lo ZIP)</summary>

1. Nel browser della VPS apri `https://github.com/nvmelessproduction/per-manuel`
2. Pulsante **`main`** in alto a sinistra → scegli **`telegram-mt5-copier`**
3. **`<> Code`** → **Download ZIP** → tasto destro sul file → **Estrai tutto**
4. Nella cartella estratta, doppio clic su **`INSTALLA.bat`**
   (se compare "Windows ha protetto il PC" → *Ulteriori informazioni* → *Esegui comunque*)
</details>

## Passo 4 – L'installazione

Si apre una finestra blu/nera che fa tutto da sola. Ecco cosa succede e cosa ti chiede:

### [1] – [3] Programma, Python e librerie — *automatico*
Copia il programma in `C:\SeersCopier`, scarica e installa Python e le librerie. Non devi fare niente (2-3 minuti).

### [4] MetaTrader 5
Ti chiede:
```
Link (oppure premi INVIO per installare MetaTrader 5 standard):
```
- Se hai il link del MetaTrader del tuo broker, incollalo (tasto destro = incolla) e premi INVIO.
- Altrimenti premi solo **INVIO**: installa il MetaTrader 5 standard, va bene per quasi tutti i broker.

Poi lo scarica e lo installa da solo (2-5 minuti). Si può aprire e chiudere da solo: è normale.

### [5] Configurazione — *qui ti fa le domande*

**1/4 TELEGRAM**
1. `Incolla il token del bot` → incolla il token del passo 2, INVIO. Controlla da solo che sia giusto.
2. Ti dice: **aggiungi il bot come amministratore del canale**. Dal telefono:
   canale → tocca il **nome del canale** in alto → **Amministratori** → **Aggiungi amministratore** → cerca lo username del bot → conferma.
   Puoi **togliergli tutti i permessi**: gli basta essere amministratore.
3. Ti dice: **pubblica un messaggio qualsiasi nel canale**. Scrivi ad esempio `test` nel canale (poi puoi cancellarlo).
4. Il programma lo vede e chiede: `Ricevuto un messaggio dal canale 'SEERS.FX' ... È quello giusto?` → **s**, INVIO.
   *(Così trova da solo l'ID del canale.)*

**2/4 METATRADER 5**
1. `Numero del conto (login)` → il numero del conto, INVIO.
2. `Password del conto` → scrivila e INVIO. **Mentre scrivi non compare niente: è normale.**
3. `Server` → il nome del server **esattamente** come nella mail del broker (es. `ICMarketsSC-Demo`), INVIO.
4. Apre MetaTrader 5, fa il login e **attiva da solo l'Algo Trading**. Aspetta circa 30 secondi.
   - Se scrive `Login non riuscito`: ricontrolla i dati e riprova. Se il server non viene trovato, in MetaTrader 5 apri *File → Apri un conto*, cerca il nome del broker, chiudi la finestra, poi torna qui e premi INVIO.
   - Se ti dice che l'**Algo Trading è spento**: in MetaTrader clicca il pulsante **Algo Trading** in alto finché diventa **verde**, poi INVIO.

**3/4 STRUMENTO**
- `Il tuo broker chiama l'oro 'XAUUSD'. Corretto?` → di solito **INVIO** (sì). Lo trova da solo.

**4/4 RISCHIO E MODALITÀ**
1. **Quante posizioni per segnale**: `1` = due posizioni (TP1 e TP2), `2` = una sola (rischio dimezzato).
   Ti mostra anche un esempio di **quanto rischi** con il lotto minimo: con un conto piccolo leggilo bene.
2. **Come calcolo il lotto**: `1` = percentuale del conto, `2` = lotto fisso. Poi il valore.
3. **Lotto massimo di sicurezza**: INVIO va bene.
4. **Modalità**: `1` = **PROVA** (non apre ordini veri, scrive solo cosa farebbe), `2` = **REALE**.
   👉 La prima volta scegli **PROVA**.

Alla fine ti mostra un riepilogo.

### [6] Avvio automatico — *automatico*
Fa in modo che il programma parta da solo ogni volta che Windows si avvia.

### [7] Ripartenza dopo un riavvio della VPS
```
Attivo l'accesso automatico? Serve la password di Windows della VPS (S/n)
```
Premi **INVIO** (sì) e scrivi la **password della VPS** (quella del Desktop remoto; anche qui non si vede mentre scrivi).
Così, se la VPS si riavvia (aggiornamenti di Windows, manutenzione), riparte **tutto da solo**: Windows, MetaTrader 5 e il programma.

### [8] Avvio — *automatico*
Si apre una **finestra nera** con scritto `Copiatore segnali Telegram - MT5 (NON CHIUDERE)`: è il programma che lavora. **Non chiuderla.**
Premi INVIO sulla finestra dell'installazione per chiuderla.

✅ **Fatto.** Ora puoi chiudere il Desktop remoto con la **X**.

---

## Passo 5 – Controllare che funzioni

Nella finestra nera devi vedere righe come:
```
Connesso a MT5: conto 12345678 (Broker-Server), saldo 1000.00 EUR
MODALITÀ DRY RUN: nessun ordine reale verrà inviato
Bot @seersfxbot in ascolto sul canale -1001234567890
```

Quando nel canale arriva un segnale, compare:
```
Segnale riconosciuto: Signal(side='SELL', symbol='XAUUSD', ...)
[DRY RUN] order_send {...}
```
In modalità PROVA non apre niente: controlla solo che lotti, SL e TP siano quelli giusti.

**Per provare subito senza aspettare un segnale vero** (e senza disturbare gli iscritti):
crea un canale privato di prova, aggiungi lo stesso bot come amministratore, lancia `CONFIGURA.bat`
e alla domanda del canale pubblica il messaggio nel canale di prova. Poi pubblica lì un segnale nello stesso formato con
**prezzi vicini a quello attuale dell'oro**. Finite le prove, rilancia `CONFIGURA.bat` e scegli di nuovo il canale vero.

---

## Passo 6 – Passare agli ordini veri

Dopo qualche giorno in PROVA (meglio ancora qualche giorno con ordini veri su conto **demo**):
1. Collegati alla VPS.
2. Doppio clic su **`C:\SeersCopier\CONFIGURA.bat`**.
3. Rispondi alle domande (INVIO per tenere i valori di prima) e alla fine scegli **2 = REALE**.
4. Il programma riparte da solo con la nuova configurazione.

---

## Uso quotidiano

| Voglio… | Cosa fare |
|---|---|
| Vedere cosa sta facendo | Collegati alla VPS e guarda la finestra nera, oppure apri `C:\SeersCopier\bot.log` |
| Cambiare rischio, conto, canale, PROVA/REALE | Doppio clic su `C:\SeersCopier\CONFIGURA.bat` |
| Fermarlo | Chiudi la finestra nera |
| Riaccenderlo | Riavvia la VPS, oppure doppio clic su `C:\SeersCopier\avvia.bat` |
| Aggiornarlo a una nuova versione | Doppio clic su `C:\SeersCopier\AGGIORNA.bat` (o rilancia il comando del passo 3). Alla domanda *"Vuoi rifarla?"* premi **INVIO** (= no): tiene la configurazione |

Le posizioni aperte dal programma in MT5 hanno il commento `sfx…-TP1` / `sfx…-TP2`.
Puoi anche chiuderle o modificarle a mano da MT5 senza problemi.

---

## Problemi comuni

| Cosa vedi | Soluzione |
|---|---|
| "Windows ha protetto il PC" | *Ulteriori informazioni → Esegui comunque* |
| `Token non valido` | Ricopia il token da @BotFather (tutto, compresa la parte prima dei `:`) |
| Il programma non vede il messaggio di prova nel canale | Il bot deve essere **amministratore** del canale (non solo iscritto). Pubblica di nuovo il messaggio |
| `Login non riuscito` | Numero conto, password o server sbagliati. Il server deve essere identico (maiuscole, trattini) |
| `Algo Trading è spento` / errore `10027` | In MT5 clicca **Algo Trading** in alto finché è verde |
| Conto **NETTING** | Il programma usa automaticamente 1 sola posizione per segnale |
| `Segnale scartato: prezzo attuale fuori dai livelli` | Normale: quando è arrivato il segnale il prezzo era già oltre lo SL o il TP1 |
| `Il rischio impostato richiederebbe meno del lotto minimo` | Conto piccolo: apre il lotto minimo, il rischio reale è più alto della percentuale scelta |
| Errore `10019` | Margine insufficiente |
| Errore `10018` | Mercato chiuso (weekend) |
| Errore `10016` | Stop troppo vicini al prezzo per le regole del broker |
| Dopo un riavvio non riparte | Al passo [7] l'accesso automatico non è stato attivato: rilancia il comando del passo 3 e rispondi **S** |

In caso di problemi manda il file **`C:\SeersCopier\bot.log`** (o uno screenshot della finestra nera).

## Sicurezza

- `C:\SeersCopier\config.json` contiene **token del bot** e **password del conto MT5**: non condividerlo.
- La password di Windows per l'accesso automatico è salvata **cifrata** da Windows (strumento ufficiale Microsoft *Autologon*).
- Il bot Telegram può solo **leggere** il canale: non può scrivere né modificare niente se gli togli i permessi.
