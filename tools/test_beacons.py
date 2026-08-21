"""Pruefungen fuer beacons.py -- ohne Discord, ohne laufende Agenten."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import beacons  # noqa: E402


def eintrag(**abweichung):
    daten = {
        "v": 1, "client": "codex", "display_name": "OpenAI Codex",
        "state": "working", "action": "editing", "model": "GPT-5.6 Sol",
        "session_start": 1000, "updated_at": 2000, "file_kind": "python",
    }
    daten.update(abweichung)
    return daten


class Pruefen(unittest.TestCase):

    def test_gueltig(self):
        self.assertIsNotNone(beacons.pruefen(eintrag(), "codex"))

    def test_unbekannter_schluessel(self):
        d = eintrag()
        d["extra"] = 1
        self.assertIsNone(beacons.pruefen(d, "codex"))

    def test_slug_passt_nicht(self):
        self.assertIsNone(beacons.pruefen(eintrag(), "antigravity"))

    def test_freitext_als_aktion(self):
        self.assertIsNone(beacons.pruefen(eintrag(action="malt Bilder"),
                                          "codex"))

    def test_millisekunden(self):
        self.assertIsNone(beacons.pruefen(eintrag(updated_at=1.5), "codex"))


class Verfall(unittest.TestCase):

    def test_frisch_bleibt(self):
        e = beacons.verfallen(eintrag(updated_at=1000), 1010)
        self.assertEqual(e["state"], "working")

    def test_stale_wird_waiting(self):
        e = beacons.verfallen(eintrag(updated_at=1000), 1100)
        self.assertEqual(e["state"], "waiting")
        self.assertEqual(e["action"], "editing")

    def test_lange_still_wird_idle(self):
        e = beacons.verfallen(eintrag(updated_at=1000), 1300)
        self.assertEqual(e["state"], "idle")
        self.assertIsNone(e["file_kind"])

    def test_leiche_faellt_raus(self):
        self.assertIsNone(beacons.verfallen(eintrag(updated_at=1000), 2000))


class Rahmen(unittest.TestCase):

    def test_working_schlaegt_waiting(self):
        a = eintrag(client="codex", state="waiting", updated_at=9999)
        b = eintrag(client="claude", state="working", updated_at=1)
        self.assertEqual(beacons.rahmen_waehlen([a, b])["client"], "claude")

    def test_juengster_working_gewinnt(self):
        a = eintrag(client="codex", updated_at=100)
        b = eintrag(client="claude", updated_at=200)
        self.assertEqual(beacons.rahmen_waehlen([a, b])["client"], "claude")

    def test_fremder_im_leerlauf_bekommt_den_rahmen(self):
        # Antigravity offen, aber untaetig: Discord soll den Namen zeigen,
        # so wie Claude Desktop im Leerlauf seinen Namen zeigt.
        a = eintrag(client="codex", state="idle", action="idle")
        self.assertEqual(beacons.rahmen_waehlen([a])["client"], "codex")

    def test_eigener_leerlauf_bekommt_ihn_nicht(self):
        a = eintrag(client="claude", state="idle", action="idle")
        self.assertIsNone(beacons.rahmen_waehlen([a]))

    def test_arbeit_schlaegt_fremden_leerlauf(self):
        a = eintrag(client="codex", state="idle", action="idle",
                    updated_at=9999)
        b = eintrag(client="claude", state="working", updated_at=1)
        self.assertEqual(beacons.rahmen_waehlen([a, b])["client"], "claude")

    def test_leer(self):
        self.assertIsNone(beacons.rahmen_waehlen([]))


class Texte(unittest.TestCase):

    def test_dateiart(self):
        self.assertEqual(beacons.zeile_taetigkeit(eintrag()),
                         "OpenAI Codex · editing a Python file")

    def test_unbekannte_art(self):
        self.assertEqual(beacons.zeile_taetigkeit(eintrag(file_kind="other")),
                         "OpenAI Codex · editing a file")

    def test_art_nur_bei_lesen_und_schreiben(self):
        e = eintrag(action="running_tests", file_kind=None)
        self.assertEqual(beacons.zeile_taetigkeit(e),
                         "OpenAI Codex · running tests")

    def test_sitzung_ohne_modell(self):
        self.assertIsNone(beacons.zeile_sitzung(eintrag(model=None)))

    def test_leerlauf_zeigt_nur_den_namen(self):
        e = eintrag(state="idle", action="idle", file_kind=None)
        self.assertEqual(beacons.zeile_taetigkeit(e), "OpenAI Codex")

    def test_abo_je_client_wird_ergaenzt(self):
        cfg = {"client_plans": {"codex": "ChatGPT Plus"}}
        teile = beacons.zeilen_sitzung(eintrag(), cfg)
        self.assertEqual(teile[-1], "Abonnement: ChatGPT Plus")

    def test_abo_eines_anderen_clients_greift_nicht(self):
        cfg = {"client_plans": {"antigravity": "Google AI Pro"}}
        teile = beacons.zeilen_sitzung(eintrag(model=None), cfg)
        self.assertEqual(teile, [])


class PoolLesen(unittest.TestCase):

    def test_beistelldatei_wird_ignoriert(self):
        with tempfile.TemporaryDirectory() as tmp:
            ordner = Path(tmp) / "beacons"
            ordner.mkdir()
            jetzt = 2000
            (ordner / "codex.json").write_text(
                json.dumps(eintrag()), encoding="utf-8")
            # Genau die Datei, die der Codex-Connector daneben ablegt.
            (ordner / "codex.state.json").write_text(
                json.dumps({"irgendwas": 1}), encoding="utf-8")
            pool = beacons.Pool(Path(tmp), systemweit=False)
            gelesen = pool.lesen(jetzt)
            self.assertEqual([e["client"] for e in gelesen], ["codex"])
            # Und keine Warnung ueber die Beistelldatei:
            self.assertEqual(pool._gemeldet, set())

    def test_juengster_ordner_gewinnt(self):
        # Windows leitet %LOCALAPPDATA% fuer Store-Apps um: derselbe Client
        # kann in zwei Ordnern liegen. Der frischere Eintrag zaehlt, nicht
        # der aus dem zuerst durchsuchten Ordner.
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            alt, neu = Path(a) / "beacons", Path(b) / "beacons"
            alt.mkdir()
            neu.mkdir()
            (alt / "codex.json").write_text(
                json.dumps(eintrag(action="thinking", updated_at=1000)),
                encoding="utf-8")
            (neu / "codex.json").write_text(
                json.dumps(eintrag(action="reading", updated_at=1990)),
                encoding="utf-8")
            pool = beacons.Pool(Path(a), systemweit=False)
            pool.ordner = [alt, neu]
            gelesen = pool.lesen(2000)
            self.assertEqual(len(gelesen), 1)
            self.assertEqual(gelesen[0]["action"], "reading")


if __name__ == "__main__":
    unittest.main()
