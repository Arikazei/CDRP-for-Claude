"""Pruefungen fuer die Denkstufe -- gegen die Messung vom 23.08.2026."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CLAUDE_RPC_DATA_DIR", tempfile.mkdtemp())
import claude_rpc  # noqa: E402

stufe_text = claude_rpc.stufe_text


class Stufe(unittest.TestCase):
    """Die sechs gemessenen Menueeintraege, eins zu eins."""

    def test_niedrig(self):
        # sessionSettings stand hier auf null: nie angefasst, nicht "aus".
        self.assertEqual(
            stufe_text({"effort": "low", "sessionSettings": None}), "low")

    def test_mittel(self):
        self.assertEqual(
            stufe_text({"effort": "medium",
                        "sessionSettings": {"ultracode": False}}), "medium")

    def test_hoch(self):
        self.assertEqual(
            stufe_text({"effort": "high",
                        "sessionSettings": {"ultracode": False}}), "high")

    def test_extra(self):
        self.assertEqual(
            stufe_text({"effort": "xhigh",
                        "sessionSettings": {"ultracode": False}}), "xhigh")

    def test_max(self):
        self.assertEqual(
            stufe_text({"effort": "max",
                        "sessionSettings": {"ultracode": False}}), "max")

    def test_ultracode(self):
        self.assertEqual(
            stufe_text({"effort": "xhigh",
                        "sessionSettings": {"ultracode": True}}),
            "xhigh +ultracode")

    def test_extra_und_ultracode_sind_unterscheidbar(self):
        # Beide sind xhigh. Wer nur effort liest, verwechselt sie.
        extra = stufe_text({"effort": "xhigh",
                            "sessionSettings": {"ultracode": False}})
        ultra = stufe_text({"effort": "xhigh",
                            "sessionSettings": {"ultracode": True}})
        self.assertNotEqual(extra, ultra)

    def test_null_und_false_sind_dasselbe(self):
        self.assertEqual(
            stufe_text({"effort": "low", "sessionSettings": None}),
            stufe_text({"effort": "low",
                        "sessionSettings": {"ultracode": False}}))


class Muell(unittest.TestCase):
    """Was nicht wie eine Stufe aussieht, kommt nicht in die Presence."""

    def test_fehlt(self):
        self.assertIsNone(stufe_text({}))

    def test_leer(self):
        self.assertIsNone(stufe_text({"effort": ""}))

    def test_keine_zeichenkette(self):
        self.assertIsNone(stufe_text({"effort": 3}))

    def test_zu_lang(self):
        self.assertIsNone(stufe_text({"effort": "x" * 20}))

    def test_zeilenumbruch(self):
        self.assertIsNone(stufe_text({"effort": "max\nnoch etwas"}))

    def test_unbekannte_stufe_wird_durchgelassen(self):
        # Kommt eine neue Stufe dazu, soll sie erscheinen, ohne dass
        # jemand erst eine Liste pflegen muss. Die Datei gehoert der App
        # selbst, nicht einem fremden Produzenten -- das Risiko ist die
        # Form, nicht die Herkunft.
        self.assertEqual(stufe_text({"effort": "ultra-max"}), "ultra-max")

    def test_kaputte_einstellungen_stoeren_nicht(self):
        self.assertEqual(stufe_text({"effort": "max",
                                     "sessionSettings": "kaputt"}), "max")


if __name__ == "__main__":
    unittest.main()
