#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit-Tests fuer den Antigravity Beacon-Connector.
Prueft Parser, Positivliste, Endungs-Mapping und Spezifikationskonformitaet.
"""

import json
import os
import tempfile
import unittest

from connectors.antigravity.watcher import (
    AntigravityWatcher,
    ENDUNG_ZU_DATEIART,
    ermittle_file_kind,
    parse_modell_name,
    DATEIARTEN,
    AKTIONEN,
    ZUSTAENDE,
)
from tools.validate_beacon import pruefe, pruefe_werte


class TestAntigravityConnector(unittest.TestCase):

    def setUp(self):
        # Hermetisch: der Waechter schreibt bei jeder verarbeiteten Zeile
        # einen Beacon. Ohne Wegwerfordner landete der im echten
        # Datenordner -- am 06.09.2026 stand nach einem Testlauf
        # "Google Antigravity - running tests" in der Presence.
        self.temp = tempfile.TemporaryDirectory()
        self.alter_ordner = os.environ.get("CLAUDE_RPC_DATA_DIR")
        os.environ["CLAUDE_RPC_DATA_DIR"] = self.temp.name

    def tearDown(self):
        if self.alter_ordner is None:
            os.environ.pop("CLAUDE_RPC_DATA_DIR", None)
        else:
            os.environ["CLAUDE_RPC_DATA_DIR"] = self.alter_ordner
        self.temp.cleanup()

    def test_file_kind_mapping(self):
        """Prueft, dass alle Endungen ausschliesslich auf erlaubte Marken abbilden."""
        for ext, art in ENDUNG_ZU_DATEIART.items():
            self.assertIn(art, DATEIARTEN, f"Ungueltige Marke {art} fuer Endung {ext}")

        self.assertEqual(ermittle_file_kind("C:\\secret\\path\\app.py"), "python")
        self.assertEqual(ermittle_file_kind("/home/user/code/README.md"), "markdown")
        self.assertEqual(ermittle_file_kind("X:\\project\\data.jsonl"), "json")
        self.assertEqual(ermittle_file_kind("unknown_file.xyz123"), "other")
        self.assertEqual(ermittle_file_kind("no_extension_file"), "other")
        self.assertIsNone(ermittle_file_kind(None))
        self.assertIsNone(ermittle_file_kind(""))

    def test_model_parser_directionality(self):
        """Prueft, dass bei Einstellungswechseln (from X to Y) nur das Zielmodell nach 'to' ausgewertet wird."""
        # Pro -> Flash
        self.assertEqual(
            parse_modell_name("The user changed setting Model Selection from Gemini 3 Pro to Gemini 3.7 Flash (High)"),
            "Gemini 3.7 Flash"
        )
        # Flash -> Pro (wichtig: darf nicht Flash ergeben!)
        self.assertEqual(
            parse_modell_name("The user changed setting Model Selection from Gemini 3.7 Flash to Gemini 3 Pro"),
            "Gemini 3 Pro"
        )
        # None -> Flash
        self.assertEqual(
            parse_modell_name("The user changed setting Model Selection from None to Gemini 3.7 Flash (High)"),
            "Gemini 3.7 Flash"
        )
        # Einfacher Modellstring
        self.assertEqual(parse_modell_name("Gemini 3 Pro"), "Gemini 3 Pro")
        self.assertIsNone(parse_modell_name(None))
        self.assertIsNone(parse_modell_name(""))

    def test_model_parser_kennt_keine_liste(self):
        """Ein neues Modell erkennt sich selbst; Sonderzeichen fliegen raus."""
        self.assertEqual(
            parse_modell_name("<USER_SETTINGS_CHANGE>The user changed setting "
                              "Model Selection from Gemini 3 Pro to Astra 6"
                              "</USER_SETTINGS_CHANGE>"),
            "Astra 6")
        self.assertEqual(parse_modell_name("changed Model Selection to Gemini 4.1 Ultra (Max)."),
                         "Gemini 4.1 Ultra")
        self.assertIsNone(parse_modell_name("changed Model Selection to C:/geheim/x.py"))
        self.assertIsNone(parse_modell_name("changed Model Selection to " + "x" * 50))

    def test_unlesbares_modell_loescht_den_alten_wert(self):
        watcher = AntigravityWatcher()
        watcher.aktuelles_modell = "Gemini 3 Pro"
        watcher.verarbeite_zeile(json.dumps({
            "type": "SYSTEM_MESSAGE", "source": "SYSTEM",
            "content": "<USER_SETTINGS_CHANGE>The user changed setting Model "
                       "Selection from Gemini 3 Pro to ???</USER_SETTINGS_CHANGE>"}))
        self.assertIsNone(watcher.aktuelles_modell)

    def test_beacon_schema_with_null_model(self):
        """Prueft, dass ein ungesetzter Modellname (None/null) voellig valide ist."""
        watcher = AntigravityWatcher()
        self.assertIsNone(watcher.aktuelles_modell)

        payload_null_model = {
            "v": 1,
            "client": "antigravity",
            "display_name": "Google Antigravity",
            "state": "working",
            "action": "reading",
            "model": None,
            "session_start": 1787000000,
            "updated_at": 1787000010,
            "file_kind": "python",
        }
        fehler = pruefe(payload_null_model, "antigravity") + pruefe_werte(payload_null_model)
        self.assertEqual(fehler, [])

    def test_beacon_schema_and_rules(self):
        """Prueft erzeugte Payloads gegen tools/validate_beacon.py."""
        # Case 1: working reading python
        payload = {
            "v": 1,
            "client": "antigravity",
            "display_name": "Google Antigravity",
            "state": "working",
            "action": "reading",
            "model": "Gemini 3.7 Flash",
            "session_start": 1787000000,
            "updated_at": 1787000010,
            "file_kind": "python",
        }
        fehler = pruefe(payload, "antigravity") + pruefe_werte(payload)
        self.assertEqual(fehler, [])

        # Case 2: working running_tests (file_kind must be null)
        payload_test = {
            "v": 1,
            "client": "antigravity",
            "display_name": "Google Antigravity",
            "state": "working",
            "action": "running_tests",
            "model": "Gemini 3.7 Flash",
            "session_start": 1787000000,
            "updated_at": 1787000010,
            "file_kind": None,
        }
        fehler = pruefe(payload_test, "antigravity") + pruefe_werte(payload_test)
        self.assertEqual(fehler, [])

        # Case 3: idle
        payload_idle = {
            "v": 1,
            "client": "antigravity",
            "display_name": "Google Antigravity",
            "state": "idle",
            "action": "idle",
            "model": None,
            "session_start": 1787000000,
            "updated_at": 1787000010,
            "file_kind": None,
        }
        fehler = pruefe(payload_idle, "antigravity") + pruefe_werte(payload_idle)
        self.assertEqual(fehler, [])

    def test_transcript_line_parsing_positive_list(self):
        """Prueft, dass nur Metadaten gelesen werden und Prompts/Code ignoriert werden."""
        watcher = AntigravityWatcher()
        
        # Test User Input -> thinking
        line_user = json.dumps({
            "type": "USER_INPUT",
            "source": "USER_EXPLICIT",
            "content": "Super geheimer Text, der nie nach aussen darf!",
            "created_at": "2026-08-20T17:00:00Z"
        })
        watcher.verarbeite_zeile(line_user)
        self.assertEqual(watcher.aktueller_state, "working")
        self.assertEqual(watcher.aktuelle_action, "thinking")
        self.assertIsNone(watcher.aktuelles_file_kind)

        # Test view_file -> reading markdown
        line_view = json.dumps({
            "type": "PLANNER_RESPONSE",
            "source": "MODEL",
            "thinking": "Geheimer Gedankengang",
            "tool_calls": [{
                "name": "view_file",
                "args": {"AbsolutePath": "C:\\TopSecret\\CustomerData.md", "StartLine": 1}
            }]
        })
        watcher.verarbeite_zeile(line_view)
        self.assertEqual(watcher.aktueller_state, "working")
        self.assertEqual(watcher.aktuelle_action, "reading")
        self.assertEqual(watcher.aktuelles_file_kind, "markdown")

        # Test edit_file -> editing python
        line_edit = json.dumps({
            "type": "PLANNER_RESPONSE",
            "source": "MODEL",
            "tool_calls": [{
                "name": "replace_file_content",
                "args": {"TargetFile": "X:\\SecretProject\\server.py", "Instruction": "Add secret"}
            }]
        })
        watcher.verarbeite_zeile(line_edit)
        self.assertEqual(watcher.aktueller_state, "working")
        self.assertEqual(watcher.aktuelle_action, "editing")
        self.assertEqual(watcher.aktuelles_file_kind, "python")

        # Test run_command test -> running_tests
        line_test = json.dumps({
            "type": "PLANNER_RESPONSE",
            "source": "MODEL",
            "tool_calls": [{
                "name": "run_command",
                "args": {"CommandLine": "pytest tests/test_core.py -v"}
            }]
        })
        watcher.verarbeite_zeile(line_test)
        self.assertEqual(watcher.aktueller_state, "working")
        self.assertEqual(watcher.aktuelle_action, "running_tests")
        self.assertIsNone(watcher.aktuelles_file_kind)

        # Test System Message Settings Change -> Model update
        line_sys = json.dumps({
            "type": "SYSTEM_MESSAGE",
            "source": "SYSTEM",
            "content": "<USER_SETTINGS_CHANGE>The user changed setting Model Selection from Gemini 3.7 Flash to Gemini 3 Pro</USER_SETTINGS_CHANGE>"
        })
        watcher.verarbeite_zeile(line_sys)
        self.assertEqual(watcher.aktuelles_modell, "Gemini 3 Pro")


if __name__ == "__main__":
    unittest.main()
