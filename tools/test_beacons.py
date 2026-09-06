"""Pruefungen fuer beacons.py -- ohne Discord, ohne laufende Agenten."""
import json
import os
import sys
import tempfile
import time
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

    def test_modell_mit_klammern_besteht_sender_und_pruefer(self):
        # Die Vereinigung der frueheren Muster: "GPT-5 (Preview)" war beim
        # Produzenten gueltig und beim Pruefer verboten. Jetzt ueberall gleich.
        d = eintrag(model="GPT-5 (Preview)")
        self.assertEqual(beacons.pruefen(d, "codex")["model"], "GPT-5 (Preview)")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import validate_beacon
        self.assertEqual(validate_beacon.pruefe_werte(d), [])

    def test_modell_ueber_40_zeichen_faellt_ueberall_weg(self):
        d = eintrag(model="A" * 41)
        self.assertIsNone(beacons.pruefen(d, "codex")["model"])
        self.assertIsNone(beacons.modell_saeubern("A" * 41))
        self.assertEqual(beacons.modell_saeubern("A" * 40), "A" * 40)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import validate_beacon
        self.assertTrue(any("model" in f for f in validate_beacon.pruefe_werte(d)))

    def test_modell_mit_satzzeichen_kostet_nur_das_modell(self):
        d = eintrag(model="rm -rf /; echo")
        geprueft = beacons.pruefen(d, "codex")
        self.assertIsNotNone(geprueft)
        self.assertIsNone(geprueft["model"])

    def test_anzeigename_muss_dem_muster_folgen(self):
        self.assertIsNone(beacons.pruefen(eintrag(display_name="Codex\nZeile 2"), "codex"))
        self.assertIsNone(beacons.pruefen(eintrag(display_name="C" * 33), "codex"))
        self.assertIsNotNone(beacons.pruefen(eintrag(display_name="OpenAI Codex (Beta)"), "codex"))

    def test_eigener_beacon_faellt_auf_vorgabe_zurueck(self):
        with tempfile.TemporaryDirectory() as d:
            beacons.eigenen_schreiben(Path(d), "idle", "idle", None, None,
                                      display_name="Claude\tDesktop!!")
            daten = json.loads((Path(d) / "beacons" / "claude.json").read_text("utf-8"))
            self.assertEqual(daten["display_name"], beacons.EIGENER_NAME)
            self.assertIsNotNone(beacons.pruefen(daten, "claude"))


class ModellAusSlug(unittest.TestCase):

    def test_regel_statt_tabelle(self):
        f = beacons.modell_aus_slug
        self.assertEqual(f("gpt-6-astra"), "GPT-6 Astra")
        self.assertEqual(f("gpt-5.6-sol"), "GPT-5.6 Sol")
        self.assertEqual(f("gpt-5.1-codex-max"), "GPT-5.1 Codex Max")
        self.assertEqual(f("gpt-5"), "GPT-5")
        self.assertEqual(f("GPT-6-Astra"), "GPT-6 Astra")
        self.assertEqual(f("gpt-5.6-sol-20260801"), "GPT-5.6 Sol")

    def test_kein_bezeichner_bleibt_wie_er_ist(self):
        f = beacons.modell_aus_slug
        self.assertEqual(f("Astra 6"), "Astra 6")
        self.assertEqual(f("Gemini 3.7 Flash"), "Gemini 3.7 Flash")
        self.assertEqual(f("o3"), "o3")
        self.assertEqual(f("GPT-5 (Preview)"), "GPT-5 (Preview)")
        self.assertIsNone(f(None))


class EinMusterNichtFuenf(unittest.TestCase):

    def test_muster_wohnen_nur_in_beacons(self):
        # Vorher stand dasselbe Muster an fuenf Stellen in drei Fassungen,
        # und Pruefer und Vertrag verwarfen gueltige Beacons. Jede zweite
        # Fassung im Repo ist ein Fehler.
        wurzel = Path(beacons.__file__).resolve().parent
        verdaechtig = ("[A-Za-z0-9]", "A-Za-z0-9 .", "A-Za-z0-9 _")
        treffer = []
        for pfad in wurzel.rglob("*.py"):
            teile = pfad.relative_to(wurzel).parts
            if teile[0] in (".venv", "build", "dist", "__pycache__"):
                continue
            if pfad.name in ("beacons.py", "test_beacons.py"):
                continue
            text = pfad.read_text("utf-8", errors="replace")
            for muster in verdaechtig:
                if muster in text:
                    treffer.append("%s: %s" % ("/".join(teile), muster))
        self.assertEqual(treffer, [])

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

    def test_eigener_name_ist_einstellbar(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            beacons.eigenen_schreiben(d, "working", "thinking", None, 1,
                                      display_name="Claude auf dem Turm")
            daten = json.loads(
                (d / "beacons" / "claude.json").read_text(encoding="utf-8"))
            self.assertEqual(daten["display_name"], "Claude auf dem Turm")

    def test_leerer_name_faellt_auf_die_vorgabe_zurueck(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            beacons.eigenen_schreiben(d, "working", "thinking", None, 1,
                                      display_name="")
            daten = json.loads(
                (d / "beacons" / "claude.json").read_text(encoding="utf-8"))
            self.assertEqual(daten["display_name"], beacons.EIGENER_NAME)

    def test_leerlauf_zeigt_nur_den_namen(self):
        e = eintrag(state="idle", action="idle", file_kind=None)
        self.assertEqual(beacons.zeile_taetigkeit(e), "OpenAI Codex")

    def test_abo_je_client_wird_ergaenzt(self):
        cfg = {"client_plans": {"codex": "ChatGPT Plus"}}
        teile = beacons.zeilen_sitzung(eintrag(), cfg)
        self.assertEqual(teile[-1], "Abonnement: ChatGPT Plus")

    def test_hersteller_faellt_in_zeile_zwei_weg(self):
        # Zeile 1 nennt "Google Antigravity" bereits vollstaendig.
        e = eintrag(client="antigravity", display_name="Google Antigravity",
                    model="Gemini 3.7 Flash High")
        self.assertEqual(beacons.zeilen_sitzung(e)[0],
                         "using Antigravity with Gemini 3.7 Flash High")

    def test_name_ohne_hersteller_bleibt_ganz(self):
        e = eintrag(client="claude", display_name="Claude Desktop",
                    model="Opus")
        self.assertEqual(beacons.zeilen_sitzung(e)[0],
                         "using Claude Desktop with Opus")

    def test_reiner_herstellername_bleibt_stehen(self):
        e = eintrag(client="x", display_name="Google", model="Gemini")
        self.assertEqual(beacons.zeilen_sitzung(e)[0],
                         "using Google with Gemini")

    def test_abo_eines_anderen_clients_greift_nicht(self):
        cfg = {"client_plans": {"antigravity": "Google AI Pro"}}
        teile = beacons.zeilen_sitzung(eintrag(model=None), cfg)
        self.assertEqual(teile, [])


class Zusatzfelder(unittest.TestCase):
    """Vertrag 1.1: plan und usage sind freiwillig und eng gefasst."""

    def test_ohne_zusatz_weiter_gueltig(self):
        self.assertIsNotNone(beacons.pruefen(eintrag(), "codex"))

    def test_plan_wird_uebernommen(self):
        e = eintrag()
        e["plan"] = "Google AI Pro"
        self.assertEqual(beacons.pruefen(e, "codex")["plan"], "Google AI Pro")

    def test_zu_langer_plan_fliegt_raus_beacon_bleibt(self):
        e = eintrag()
        e["plan"] = "x" * 40
        geprueft = beacons.pruefen(e, "codex")
        self.assertIsNotNone(geprueft)
        self.assertNotIn("plan", geprueft)

    def test_plan_mit_zeilenumbruch_fliegt_raus(self):
        # Sonst koennte ein Produzent eine zweite Zeile in die Presence
        # schreiben, an der Vorlage des Masters vorbei.
        e = eintrag()
        e["plan"] = "Pro\nirgendwas"
        self.assertNotIn("plan", beacons.pruefen(e, "codex"))

    def test_usage_nur_ganze_prozente(self):
        e = eintrag()
        e["usage"] = {"five_hour": 8, "week": 3, "monat": 5}
        sauber = beacons.pruefen(e, "codex")["usage"]
        self.assertEqual(sauber, {"five_hour": 8, "week": 3})

    def test_usage_ausserhalb_der_spanne(self):
        e = eintrag()
        e["usage"] = {"five_hour": 140, "week": -1}
        self.assertNotIn("usage", beacons.pruefen(e, "codex"))

    def test_unbekanntes_feld_verwirft_alles(self):
        e = eintrag()
        e["nachricht"] = "hallo"
        self.assertIsNone(beacons.pruefen(e, "codex"))

    def test_zeile_zeigt_auslastung_und_abo(self):
        e = eintrag(model=None)
        e["usage"] = {"five_hour": 8, "week": 3}
        e["plan"] = "Google AI Pro"
        self.assertEqual(beacons.zeilen_sitzung(e),
                         ["5h 8% · Woche 3%", "Abonnement: Google AI Pro"])

    def test_abgelesenes_abo_schlaegt_handeintrag(self):
        e = eintrag(model=None)
        e["plan"] = "Google AI Ultra"
        cfg = {"client_plans": {"codex": "von Hand"}}
        self.assertEqual(beacons.zeilen_sitzung(e, cfg),
                         ["Abonnement: Google AI Ultra"])


class Vorrang(unittest.TestCase):
    """Wer sendet, wenn Dienst und Extension gleichzeitig laufen?"""

    def test_dienst_schlaegt_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            beacons.sender_melden(d, "standalone", pid=4711)
            fremd = beacons.fremder_sender(d, "extension", eigene_pid=99,
                                           systemweit=False)
            self.assertEqual(fremd["rolle"], "standalone")

    def test_extension_verdraengt_den_dienst_nicht(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            beacons.sender_melden(d, "extension", pid=4711)
            self.assertIsNone(beacons.fremder_sender(
                d, "standalone", eigene_pid=99, systemweit=False))

    def test_eigener_eintrag_zaehlt_nicht(self):
        # Sonst wiche jeder Prozess vor sich selbst zurueck.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            beacons.sender_melden(d, "standalone", pid=4711)
            self.assertIsNone(beacons.fremder_sender(
                d, "standalone", eigene_pid=4711, systemweit=False))

    def test_alter_eintrag_gilt_nicht(self):
        # Der Dienst ist abgestuerzt: die Extension muss uebernehmen.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            beacons.sender_melden(d, "standalone", pid=4711)
            spaeter = time.time() + beacons.SENDER_FRISCH + 1
            self.assertIsNone(beacons.fremder_sender(
                d, "extension", eigene_pid=99, jetzt=spaeter,
                systemweit=False))

    def test_abmelden_gibt_frei(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            beacons.sender_melden(d, "standalone", pid=4711)
            beacons.sender_abmelden(d, "standalone")
            self.assertIsNone(beacons.fremder_sender(
                d, "extension", eigene_pid=99, systemweit=False))

    def test_kaputter_eintrag_blockiert_nicht(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / beacons.sender_datei("standalone")).write_text("kein json",
                                                  encoding="utf-8")
            self.assertIsNone(beacons.fremder_sender(
                d, "extension", eigene_pid=99, systemweit=False))


class Karussell(unittest.TestCase):

    EIGEN = {"details": "Claude Desktop", "start": 500, "aktiv": True,
             "zeilen": ["using cowork with Opus", "5h: 40%",
                        "Abonnement: Max (5x)"]}

    def aktive(self, eintraege, jetzt=1000, merk=None):
        # Jeder Test bekommt ein eigenes Gedaechtnis; das Modul-Gedaechtnis
        # wuerde sonst Arbeit aus einem Test in den naechsten tragen.
        return [e["client"] for e in
                beacons.aktive(eintraege, jetzt, {} if merk is None else merk)]

    def test_wartender_ohne_vorgeschichte_zaehlt_nicht(self):
        a = eintrag(client="codex", state="waiting", action="idle",
                    updated_at=9999)
        b = eintrag(client="antigravity", state="idle", action="idle")
        self.assertEqual(self.aktive([a, b]), [])

    def test_ein_arbeiter_ein_untaetiger_nur_der_arbeiter(self):
        arbeitend = eintrag(client="codex", state="working")
        untaetig = eintrag(client="claude", state="waiting", action="thinking",
                           updated_at=9999)
        self.assertEqual(self.aktive([arbeitend, untaetig]), ["codex"])

    def test_mehrere_arbeitende_kommen_alle_dran(self):
        # Der Kern der Fehler vom 22.08.: erst gewann der haeufigste
        # Schreiber, dann der bisherige Besitzer. Beide Male war Codex
        # nie zu sehen, obwohl er arbeitete. Jetzt sind beide dabei.
        codex = eintrag(client="codex", state="working", updated_at=100)
        claude = eintrag(client="claude", state="working", updated_at=999)
        self.assertEqual(self.aktive([codex, claude]), ["claude", "codex"])

    def test_reihenfolge_haengt_nicht_am_zeitstempel(self):
        # Sonst huepfte die Anzeige zufaellig, weil der Wechsel an der
        # Uhrzeit haengt und die Liste sich staendig umsortieren wuerde.
        a = eintrag(client="codex", state="working", updated_at=999)
        b = eintrag(client="antigravity", state="working", updated_at=1)
        self.assertEqual(self.aktive([a, b]), ["antigravity", "codex"])

    def test_wartender_verdraengt_keinen_arbeitenden(self):
        wartend = eintrag(client="antigravity", state="waiting", action="idle",
                          updated_at=9999)
        arbeitend = eintrag(client="codex", state="working", updated_at=1)
        self.assertEqual(self.aktive([wartend, arbeitend]), ["codex"])

    def test_keiner_arbeitet_dann_alle_offenen(self):
        # Die aktive Menge ist leer; der Aufrufer nimmt dann alle.
        alle = [eintrag(client="codex", state="waiting", action="idle"),
                eintrag(client="antigravity", state="idle", action="idle")]
        self.assertEqual(self.aktive(alle), [])
        liste = beacons.karten(self.EIGEN, alle)
        self.assertEqual(sorted({k["client"] for k in liste}),
                         ["antigravity", "claude", "codex"])

    def test_nachlauf_haelt_und_laeuft_ab(self):
        # Gemessen am 06.09.2026: Codex fiel zwischen zwei Hook-Ereignissen
        # fuer eine Sekunde auf "waiting", und Claude, der nur wartete,
        # stand in der Presence. Innerhalb der Frist bleibt Codex; danach
        # -- und das ist der Punkt, an dem 1.6.2 scheiterte -- faellt er
        # heraus.
        merk = {}
        claude = eintrag(client="claude", state="waiting", action="thinking",
                         updated_at=9999)
        arbeitend = eintrag(client="codex", state="working", updated_at=1000)
        self.assertEqual(self.aktive([arbeitend, claude], 1000, merk),
                         ["codex"])
        wartend = eintrag(client="codex", state="waiting", action="idle",
                          updated_at=1001)
        self.assertEqual(self.aktive([wartend, claude], 1001, merk), ["codex"])
        self.assertEqual(self.aktive([wartend, claude],
                                     1000 + beacons.NACHLAUF, merk), ["codex"])
        self.assertEqual(self.aktive([wartend, claude],
                                     1001 + beacons.NACHLAUF, merk), [])
        self.assertNotIn("codex", merk)

    def test_nachlauf_beginnt_erst_nach_arbeit(self):
        merk = {}
        wartend = eintrag(client="codex", state="waiting", action="idle",
                          updated_at=1000)
        self.assertEqual(self.aktive([wartend], 1000, merk), [])
        self.assertEqual(self.aktive([wartend], 1005, merk), [])

    def test_leerlauf_beendet_den_nachlauf_sofort(self):
        merk = {}
        self.assertEqual(self.aktive([eintrag(client="codex")], 1000, merk),
                         ["codex"])
        ruhend = eintrag(client="codex", state="idle", action="idle")
        self.assertEqual(self.aktive([ruhend], 1002, merk), [])

    def test_nachlauf_wird_durch_neue_arbeit_verlaengert(self):
        merk = {}
        self.aktive([eintrag(client="codex")], 1000, merk)
        self.aktive([eintrag(client="codex")], 1020, merk)
        wartend = eintrag(client="codex", state="waiting", action="idle")
        self.assertEqual(self.aktive([wartend], 1040, merk), ["codex"])
        self.assertEqual(self.aktive([wartend], 1046, merk), [])

    def test_genehmigungsfrage_zaehlt_als_aktiv(self):
        # Der Agent wartet auf den Nutzer -- der Moment groesster
        # Aufmerksamkeit, nicht Leerlauf. Auch ohne Vorgeschichte.
        frage = eintrag(client="codex", state="waiting",
                        action="waiting_approval")
        claude = eintrag(client="claude", state="waiting", action="thinking",
                         updated_at=9999)
        self.assertEqual(self.aktive([frage, claude]), ["codex"])
        karte = beacons.karten(None, beacons.aktive([frage], 1000, {}))[0]
        self.assertEqual(karte["details"], "OpenAI Codex · waiting for approval")
        self.assertTrue(karte["aktiv"])
        self.assertEqual(karte["start"], 1000)

    def test_zaehler_bleibt_in_der_nachlauffrist(self):
        merk = {}
        beacons.aktive([eintrag(client="codex")], 1000, merk)
        wartend = eintrag(client="codex", state="waiting", action="idle",
                          session_start=777)
        karte = beacons.karten(None, beacons.aktive([wartend], 1010, merk))[0]
        self.assertEqual(karte["start"], 777)
        self.assertTrue(karte["aktiv"])

    def test_volle_runde_durch_alle_clients(self):
        fremde = [
            eintrag(client="codex", display_name="OpenAI Codex",
                    state="idle", action="idle", model="GPT-5.6 Sol"),
            eintrag(client="antigravity", display_name="Google Antigravity",
                    state="idle", action="idle", model=None),
        ]
        liste = beacons.karten(self.EIGEN, fremde)
        # Drei Zeilen von Claude, dann Antigravity, dann Codex.
        self.assertEqual([k["client"] for k in liste],
                         ["claude", "claude", "claude",
                          "antigravity", "codex"])
        self.assertEqual(liste[3]["details"], "Google Antigravity")
        self.assertIsNone(liste[3]["zeile"])
        self.assertEqual(liste[4]["details"], "OpenAI Codex")
        self.assertEqual(liste[4]["zeile"],
                         "using Codex with GPT-5.6 Sol")

    def test_ohne_eigenen_nur_fremde(self):
        fremde = [eintrag(client="codex", state="idle", action="idle",
                          model=None)]
        liste = beacons.karten(None, fremde)
        self.assertEqual([k["client"] for k in liste], ["codex"])

    def test_ohne_rotation_eine_zeile(self):
        cfg = {"state_line": {"mode": "off"}}
        liste = beacons.karten(self.EIGEN, [], cfg)
        self.assertEqual(len(liste), 1)
        self.assertIn(" · ", liste[0]["zeile"])

    def test_wechsel_laeuft_rundherum(self):
        liste = beacons.karten(self.EIGEN, [])
        gesehen = [beacons.karte_waehlen(liste, t, 20)["zeile"]
                   for t in (0, 20, 40, 60)]
        self.assertEqual(gesehen[0], gesehen[3])
        self.assertEqual(len(set(gesehen)), 3)

    def test_takt_faellt_nie_unter_discords_grenze(self):
        # Unter 15 s leert Discord die Presence, statt zu drosseln.
        liste = beacons.karten(self.EIGEN, [])
        self.assertEqual(beacons.karte_waehlen(liste, 0, 1)["zeile"],
                         beacons.karte_waehlen(liste, 14, 1)["zeile"])

    def test_leere_liste(self):
        self.assertIsNone(beacons.karte_waehlen([], 0, 20))


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
