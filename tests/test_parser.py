import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signal_parser import parse_signal, parse_update

SEGNALE = """🦾 SEERSFX · SEGNALE ORO

🔴 VENDI ORO (XAUUSD)
📍 Zona d'ingresso: 4170 – 4175

🛑 Stop Loss: 4180
🎯 Take Profit 1: 4160
🎯 Take Profit 2: 4150

⚠️ Gestione del rischio: massimo 1–2% per operazione"""

AGGIORNAMENTO = """🦾 SEERSFX · AGGIORNAMENTO

✅ Operazione in corso
🔴 ORO in vendita: 55 pips a favore

🔒 Metti in sicurezza parte dei profitti e porta lo stop a pareggio (BE+)."""

DISCLAIMER = "⚠️ DISCLAIMER E TERMINI DI UTILIZZO DI QUESTO CANALE ..."


class TestParser(unittest.TestCase):
    def test_sell_signal(self):
        s = parse_signal(SEGNALE)
        self.assertIsNotNone(s)
        self.assertEqual(s.side, "SELL")
        self.assertEqual(s.symbol, "XAUUSD")
        self.assertEqual((s.entry_low, s.entry_high), (4170, 4175))
        self.assertEqual(s.sl, 4180)
        self.assertEqual(s.tps, [4160, 4150])

    def test_buy_signal(self):
        txt = ("🟢 COMPRA ORO (XAUUSD)\nZona d'ingresso: 4100 - 4095\n"
               "Stop Loss: 4088\nTake Profit 1: 4110\nTake Profit 2: 4120")
        s = parse_signal(txt)
        self.assertEqual(s.side, "BUY")
        self.assertEqual((s.entry_low, s.entry_high), (4095, 4100))
        self.assertEqual(s.tps, [4110, 4120])

    def test_forex_decimals(self):
        txt = "COMPRA EURUSD\nIngresso: 1,0850\nSL: 1.0820\nTP1: 1.0880\nTP2: 1.0910"
        s = parse_signal(txt)
        self.assertEqual(s.symbol, "EURUSD")
        self.assertAlmostEqual(s.entry_low, 1.085)
        self.assertEqual(s.tps, [1.088, 1.091])

    def test_incoherent_levels_rejected(self):
        self.assertIsNone(parse_signal(SEGNALE.replace("Stop Loss: 4180", "Stop Loss: 4165")))

    def test_direction_only(self):
        s = parse_signal("🔴 VENDI ORO")
        self.assertEqual((s.side, s.symbol, s.sl, s.tps), ("SELL", "XAUUSD", None, []))
        self.assertFalse(s.complete)
        self.assertEqual(parse_signal("🟢 COMPRA ORO ora").side, "BUY")
        self.assertTrue(parse_signal(SEGNALE).complete)

    def test_profit_message_is_not_signal(self):
        self.assertIsNone(parse_signal("Siamo in profitto di +40 pips, metti BE"))
        self.assertIsNone(parse_signal("ORO in vendita: 55 pips a favore"))

    def test_update_is_not_signal(self):
        self.assertIsNone(parse_signal(AGGIORNAMENTO))
        self.assertIsNone(parse_signal(DISCLAIMER))

    def test_update(self):
        u = parse_update(AGGIORNAMENTO)
        self.assertTrue(u.breakeven)
        self.assertTrue(u.partial_close)
        self.assertFalse(u.close_all)

    def test_close_and_move_sl(self):
        self.assertTrue(parse_update("Chiudi tutto ora, prendiamo profitto").close_all)
        self.assertEqual(parse_update("Sposta lo stop a 4172").new_sl, 4172)
        self.assertIsNone(parse_update(DISCLAIMER))
        self.assertIsNone(parse_update("Buongiorno a tutti, oggi mercato volatile"))


if __name__ == "__main__":
    unittest.main()
