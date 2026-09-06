"""Lokaler Vertragstest ohne echte oder gespeicherte Hook-Inhalte."""

import json
import os
import tempfile
import unittest

import codex_beacon


class BeaconTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("CLAUDE_RPC_DATA_DIR")
        os.environ["CLAUDE_RPC_DATA_DIR"] = self.temp.name

    def tearDown(self):
        if self.old_data_dir is None:
            os.environ.pop("CLAUDE_RPC_DATA_DIR", None)
        else:
            os.environ["CLAUDE_RPC_DATA_DIR"] = self.old_data_dir
        self.temp.cleanup()

    def read_beacon(self):
        path = os.path.join(self.temp.name, "beacons", "codex.json")
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def emit(self, event, now, **extra):
        payload = {
            "hook_event_name": event,
            "model": "gpt-5.6-sol-20260801",
            "cwd": "PRIVATE_CWD",
            "session_id": "PRIVATE_SESSION",
            "transcript_path": "PRIVATE_TRANSCRIPT",
            "prompt": "PRIVATE_PROMPT",
        }
        payload.update(extra)
        codex_beacon.process_payload(payload, now=now)
        return self.read_beacon()

    def test_full_state_flow_and_privacy(self):
        beacon = self.emit("SessionStart", 1000, source="startup")
        self.assertEqual((beacon["state"], beacon["action"]),
                         ("waiting", "idle"))
        self.assertEqual(beacon["session_start"], 1000)

        beacon = self.emit("UserPromptSubmit", 1001)
        self.assertEqual((beacon["state"], beacon["action"]),
                         ("working", "thinking"))

        beacon = self.emit(
            "PreToolUse", 1002, tool_name="mcp__filesystem__read_file",
            tool_input={"path": "PRIVATE_FOLDER/Project.md"})
        self.assertEqual((beacon["action"], beacon["file_kind"]),
                         ("reading", "markdown"))

        patch = "*** Begin Patch\n*** Add File: PRIVATE/Script.py\n*** End Patch"
        beacon = self.emit("PreToolUse", 1003, tool_name="apply_patch",
                           tool_input={"command": patch})
        self.assertEqual((beacon["action"], beacon["file_kind"]),
                         ("editing", "python"))

        beacon = self.emit("PreToolUse", 1004, tool_name="Bash",
                           tool_input={"command": "python -m pytest"})
        self.assertEqual((beacon["action"], beacon["file_kind"]),
                         ("running_tests", None))

        beacon = self.emit("PermissionRequest", 1005, tool_name="Bash",
                           tool_input={"command": "PRIVATE_COMMAND"})
        self.assertEqual((beacon["state"], beacon["action"]),
                         ("waiting", "waiting_approval"))

        beacon = self.emit("Stop", 1006)
        self.assertEqual((beacon["state"], beacon["action"]),
                         ("waiting", "idle"))
        beacon = self.emit("SessionEnd", 1007)
        self.assertEqual((beacon["state"], beacon["action"]),
                         ("idle", "idle"))
        self.assertIsNone(beacon["session_start"])

        beacon_path, state_path = codex_beacon.beacon_paths()
        for path in (beacon_path, state_path):
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read()
            for private in ("PRIVATE_CWD", "PRIVATE_SESSION",
                            "PRIVATE_TRANSCRIPT", "PRIVATE_PROMPT",
                            "PRIVATE_FOLDER", "Script.py", "PRIVATE_COMMAND"):
                self.assertNotIn(private, raw)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_unknown_tool_is_closed_and_model_with_symbols_dropped(self):
        self.emit("SessionStart", 2000, source="startup",
                  model="secret/model:1 (PRIVATE)")
        beacon = self.emit("PreToolUse", 2001,
                           model="secret/model:1 (PRIVATE)",
                           tool_name="private_tool",
                           tool_input={"secret": "PRIVATE"})
        self.assertEqual(beacon["action"], "running_command")
        self.assertIsNone(beacon["model"])
        self.assertIsNone(beacon["file_kind"])
        self.assertNotIn("PRIVATE", json.dumps(beacon))

    def test_new_model_passes_without_a_table_entry(self):
        # Gemessen am 06.09.2026: wochenlang stand "GPT-5.6 Sol" in der
        # Presence, waehrend laengst ein Modell lief, das die Tabelle
        # nicht kannte. Ein plausibler Name wird jetzt durchgereicht.
        beacon = self.emit("UserPromptSubmit", 3000, model="Astra 6")
        self.assertEqual(beacon["model"], "Astra 6")
        beacon = self.emit("PreToolUse", 3001, model="astra-6-preview",
                           tool_name="Bash", tool_input={"command": "ls"})
        self.assertEqual(beacon["model"], "astra-6-preview")

    def test_table_still_beautifies_known_models(self):
        beacon = self.emit("UserPromptSubmit", 3100, model="gpt-5.6-sol-20260801")
        self.assertEqual(beacon["model"], "GPT-5.6 Sol")

    def test_unknown_model_replaces_the_old_value_with_none(self):
        self.emit("UserPromptSubmit", 3200, model="gpt-5.6-sol")
        beacon = self.emit("PreToolUse", 3201, model="X:\\geheim\\modell.txt",
                           tool_name="Bash", tool_input={"command": "ls"})
        self.assertIsNone(beacon["model"])
        beacon = self.emit("PostToolUse", 3202, model=None)
        self.assertIsNone(beacon["model"])

    def test_model_survives_events_without_a_model_field(self):
        self.emit("UserPromptSubmit", 3300, model="Astra 6")
        nutzlast = {"hook_event_name": "PostToolUse"}
        codex_beacon.process_payload(nutzlast, now=3301)
        self.assertEqual(self.read_beacon()["model"], "Astra 6")

    def test_stored_state_is_checked_on_load(self):
        _, state_path = codex_beacon.beacon_paths()
        codex_beacon.atomic_json(state_path, {
            "state": "working", "action": "thinking",
            "model": "<synthetic>", "session_start": 1, "updated_at": 1,
            "file_kind": None})
        vorher = codex_beacon.normalized_previous(
            codex_beacon.load_state(state_path))
        self.assertIsNone(vorher["model"])

    def test_model_label_rules(self):
        self.assertEqual(codex_beacon.model_label("gpt-5.6-sol"), "GPT-5.6 Sol")
        self.assertEqual(codex_beacon.model_label("  Astra 6  "), "Astra 6")
        self.assertIsNone(codex_beacon.model_label("-astra"))
        self.assertIsNone(codex_beacon.model_label("a" * 41))
        self.assertIsNone(codex_beacon.model_label("Astra 6!"))
        self.assertIsNone(codex_beacon.model_label(None))
        self.assertIsNone(codex_beacon.model_label(6))


if __name__ == "__main__":
    unittest.main()
