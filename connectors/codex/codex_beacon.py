"""Schreibt Codex-Hook-Zustaende als Beacon nach SPEC-beacon-v1."""

import json
import os
import re
import sys
import time

# Der Datenordner ist die Regel des Senders (beacons.py im Repo-Stamm),
# nicht des Connectors: beide muessen denselben Ort meinen, sonst sieht
# der Sender den Beacon nie. Gefunden wird der Stamm relativ zu dieser
# Datei -- eine Kopie an anderer Stelle laeuft absichtlich nicht.
HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(os.path.dirname(HIER))
if WURZEL not in sys.path:
    sys.path.insert(0, WURZEL)
import beacons  # noqa: E402


CLIENT = "codex"
DISPLAY_NAME = "OpenAI Codex"
HEARTBEAT_SECONDS = 20

# Nur noch Verschoenerung: aus "gpt-5.6-sol" wird "GPT-5.6 Sol". Die
# Tabelle sperrt kein Modell mehr aus. Frueher war sie die einzige
# Schleuse, und ein Modell, das nicht darin stand, liess den alten Wert
# stehen -- wochenlang "GPT-5.6 Sol", waehrend laengst ein anderes lief.
MODEL_LABELS = (
    ("gpt-5.6-sol", "GPT-5.6 Sol"),
    ("gpt-5.6-terra", "GPT-5.6 Terra"),
    ("gpt-5.6-luna", "GPT-5.6 Luna"),
    ("gpt-5.5", "GPT-5.5"),
    ("gpt-5.4", "GPT-5.4"),
    ("gpt-5.3-codex", "GPT-5.3 Codex"),
    ("gpt-5.2-codex", "GPT-5.2 Codex"),
    ("gpt-5.2", "GPT-5.2"),
    ("gpt-5.1-codex-max", "GPT-5.1 Codex Max"),
    ("gpt-5.1-codex-mini", "GPT-5.1 Codex Mini"),
    ("gpt-5.1-codex", "GPT-5.1 Codex"),
    ("gpt-5.1", "GPT-5.1"),
    ("gpt-5-codex-mini", "GPT-5 Codex Mini"),
    ("gpt-5-codex", "GPT-5 Codex"),
    ("gpt-5", "GPT-5"),
    ("o4-mini", "o4-mini"),
    ("o3", "o3"),
)

# Das Tor zur Presence: nur Buchstaben, Ziffern, Punkt, Bindestrich,
# Unterstrich und Leerzeichen, erstes Zeichen alphanumerisch, hoechstens
# 40 Zeichen -- dasselbe Muster wie beim Claude-Modell (RE_MODELL_ROH).
# Ein Prompt, ein Pfad, ein Satzzeichen kommt hier nicht durch; ein
# neues Modell schon.
RE_MODELL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,39}$")

EXTENSION_KINDS = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript",
    ".cts": "typescript",
    ".md": "markdown", ".mdx": "markdown", ".markdown": "markdown",
    ".json": "json", ".jsonl": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".fish": "shell",
    ".ps1": "powershell", ".psm1": "powershell", ".psd1": "powershell",
    ".cs": "csharp", ".csproj": "csharp", ".sln": "csharp",
    ".c": "cpp", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
    ".h": "cpp", ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".rs": "rust", ".go": "go", ".java": "java",
    ".sql": "sql",
    ".txt": "text", ".log": "text", ".rst": "text",
    ".toml": "config", ".ini": "config", ".cfg": "config",
    ".conf": "config", ".env": "config", ".xml": "config",
    ".properties": "config", ".editorconfig": "config",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image", ".svg": "image",
    ".ico": "image", ".bmp": "image",
    ".csv": "data", ".tsv": "data", ".parquet": "data",
    ".xlsx": "data", ".xls": "data", ".db": "data",
    ".sqlite": "data", ".sqlite3": "data",
}

PATH_KEYS = {
    "path", "file", "filename", "file_path", "filepath", "absolute_path",
    "relative_path", "target", "destination", "dest", "source_path",
}

TEST_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(^|[;&|\s])pytest([\s;&|]|$)",
    r"python(?:3|\.exe)?\s+-m\s+(?:pytest|unittest)\b",
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b",
    r"\b(?:jest|vitest|mocha|ava)\b",
    r"\bdotnet\s+test\b", r"\bcargo\s+test\b", r"\bgo\s+test\b",
    r"\b(?:mvn|mvnw|gradle|gradlew)(?:\.cmd|\.bat)?\s+.*\btest\b",
    r"\bctest\b",
))


def data_directory():
    """CLAUDE_RPC_DATA_DIR, sonst der nicht umgeleitete Profilordner --
    siehe beacons.produzenten_datenordner."""
    return str(beacons.produzenten_datenordner())


def beacon_paths():
    folder = os.path.join(data_directory(), "beacons")
    return (os.path.join(folder, "codex.json"),
            os.path.join(folder, "codex.state.json"))


# Abo und Auslastung stehen im Einstellungsfenster der App. Sie liest
# der Waechter aus, nicht der Hook: ein Hook laeuft im Millisekundentakt
# waehrend einer Aufgabe, ein Fensterdurchlauf hat dort nichts zu
# suchen. Ablage in einer eigenen Datei, damit der Zustandsspeicher der
# Hooks unveraendert bleibt. Der Punkt im Namen ist Absicht -- der
# Master ueberliest Dateien mit Punkt im Stamm.
# Zwei Altersgrenzen, weil die beiden Angaben nicht gleich schnell
# altern. Eine Auslastung von vor drei Stunden ist eine Falschaussage.
# Eine Abo-Bezeichnung von vor drei Stunden ist einfach die
# Abo-Bezeichnung -- die aendert sich hoechstens beim Tarifwechsel.
#
# Mit einer gemeinsamen Grenze verschwand auch der Plan nach drei
# Stunden, und er kam erst zurueck, wenn der Nutzer das
# Einstellungsfenster wieder oeffnete. Genau so gemessen am 22.08.2026.
USAGE_MAX_AGE = 180 * 60
PLAN_MAX_AGE = 30 * 24 * 3600


def window_path():
    return os.path.join(data_directory(), "beacons", "codex.window.json")


def load_window(now):
    """Abgelesene Fensterwerte, sofern sie nicht zu alt sind."""
    daten = load_state(window_path())
    gelesen = daten.get("read_at")
    if not isinstance(gelesen, int):
        return {}
    alter = now - gelesen
    heraus = {}
    if (alter <= PLAN_MAX_AGE and isinstance(daten.get("plan"), str)
            and daten["plan"].strip()):
        heraus["plan"] = daten["plan"].strip()
    if alter > USAGE_MAX_AGE:
        return heraus
    nutzung = daten.get("usage")
    if isinstance(nutzung, dict):
        sauber = {k: v for k, v in nutzung.items()
                  if k in ("five_hour", "week")
                  and isinstance(v, int) and not isinstance(v, bool)
                  and 0 <= v <= 100}
        if sauber:
            heraus["usage"] = sauber
    return heraus


def atomic_json(path, value):
    """Ein fester Nachbarname stellt atomaren Ersatz auf demselben Volume sicher."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=True, separators=(",", ":"))
        handle.write("\n")
    os.replace(temporary, path)


def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    return {}


def model_label(raw_model):
    """Modellwert pruefen und aufhuebschen -- oder verwerfen.

    Besteht der Wert die Musterpruefung nicht, kommt None zurueck, und
    der Aufrufer uebernimmt das None. Ein alter Wert wird nie
    weitergefuehrt: eine Anzeige mit dem falschen Modell ist schlechter
    als eine ohne.
    """
    if not isinstance(raw_model, str):
        return None
    candidate = raw_model.strip()
    if not RE_MODELL.match(candidate):
        return None
    lowered = candidate.lower()
    for slug, label in MODEL_LABELS:
        if lowered == slug or lowered.startswith(slug + "-"):
            return label
    return candidate


def kind_from_path(path_value):
    """Der Pfad lebt nur in dieser Funktion; nur seine Endung verlaesst sie."""
    if not isinstance(path_value, str) or not path_value:
        return None
    name = path_value.rstrip("/\\")
    lower_name = os.path.basename(name).lower()
    if lower_name == ".editorconfig":
        return "config"
    extension = os.path.splitext(lower_name)[1]
    return EXTENSION_KINDS.get(extension, "other")


def patch_kind(command):
    if not isinstance(command, str):
        return None
    prefixes = ("*** Add File: ", "*** Update File: ",
                "*** Delete File: ", "+++ ")
    for line in command.splitlines():
        for prefix in prefixes:
            if line.startswith(prefix):
                candidate = line[len(prefix):].strip()
                if candidate.startswith("b/"):
                    candidate = candidate[2:]
                return kind_from_path(candidate)
    return None


def path_kind_from_value(value):
    if isinstance(value, str):
        return kind_from_path(value)
    if isinstance(value, list):
        for item in value:
            result = path_kind_from_value(item)
            if result is not None:
                return result
    return None


def input_file_kind(tool_name, tool_input):
    """Nur explizite Pfadfelder werden betrachtet, nie Befehle oder Freitext."""
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "apply_patch":
        return patch_kind(tool_input.get("command"))
    for key, value in tool_input.items():
        if isinstance(key, str) and key.lower() in PATH_KEYS:
            result = path_kind_from_value(value)
            if result is not None:
                return result
    return None


def is_test_command(tool_input):
    if not isinstance(tool_input, dict):
        return False
    command = tool_input.get("command")
    if not isinstance(command, str):
        return False
    return any(pattern.search(command) for pattern in TEST_PATTERNS)


def classify_tool(tool_name, tool_input):
    if not isinstance(tool_name, str):
        return "running_command", None
    lowered = tool_name.lower()
    if lowered == "apply_patch" or lowered in {"edit", "write"}:
        return "editing", input_file_kind(tool_name, tool_input)
    if tool_name == "Bash":
        action = "running_tests" if is_test_command(tool_input) else "running_command"
        return action, None
    if "search" in lowered and ("web" in lowered or "browser" in lowered):
        return "web_search", None
    if any(token in lowered for token in
           ("read_file", "read_text", "view_image", "open_file",
            "get_file", "load_file")):
        return "reading", input_file_kind(tool_name, tool_input)
    if any(token in lowered for token in
           ("write_file", "write_text", "edit_file", "patch_file",
            "create_file", "save_file")):
        return "editing", input_file_kind(tool_name, tool_input)
    return "running_command", None


def normalized_previous(raw):
    states = {"working", "waiting", "idle"}
    actions = {"thinking", "reading", "editing", "running_tests",
               "running_command", "web_search", "waiting_approval", "idle"}
    result = {
        "state": raw.get("state") if raw.get("state") in states else "idle",
        "action": raw.get("action") if raw.get("action") in actions else "idle",
        "model": model_label(raw.get("model")),
        "session_start": raw.get("session_start")
                         if isinstance(raw.get("session_start"), int) else None,
        "updated_at": raw.get("updated_at")
                      if isinstance(raw.get("updated_at"), int) else None,
        "file_kind": raw.get("file_kind")
                     if raw.get("file_kind") in set(EXTENSION_KINDS.values())
                     else None,
    }
    return result


def event_state(payload, previous, now):
    event = payload.get("hook_event_name")
    state = previous.copy()
    # Ein gelieferter Wert gilt immer -- auch wenn er verworfen wird und
    # das Modell damit auf None faellt. Nur wenn die Nutzlast gar kein
    # Modell nennt, bleibt der letzte Stand.
    if "model" in payload:
        state["model"] = model_label(payload.get("model"))
    state["file_kind"] = None

    if event == "SessionStart":
        source = payload.get("source")
        if source not in {"resume", "compact"} or state["session_start"] is None:
            state["session_start"] = now
        state["state"], state["action"] = "waiting", "idle"
    elif event == "UserPromptSubmit":
        if state["session_start"] is None:
            state["session_start"] = now
        state["state"], state["action"] = "working", "thinking"
    elif event == "PreToolUse":
        if state["session_start"] is None:
            state["session_start"] = now
        action, file_kind = classify_tool(payload.get("tool_name"),
                                          payload.get("tool_input"))
        state["state"], state["action"] = "working", action
        if action in {"reading", "editing"}:
            state["file_kind"] = file_kind
    elif event == "PostToolUse":
        if state["session_start"] is None:
            state["session_start"] = now
        state["state"], state["action"] = "working", "thinking"
    elif event == "PermissionRequest":
        if state["session_start"] is None:
            state["session_start"] = now
        state["state"], state["action"] = "waiting", "waiting_approval"
    elif event == "Stop":
        state["state"], state["action"] = "waiting", "idle"
    elif event == "SessionEnd":
        state["state"], state["action"] = "idle", "idle"
        state["session_start"] = None
    else:
        return None
    return state


def beacon_from_state(state, now):
    beacon = {
        "v": 1,
        "client": CLIENT,
        "display_name": DISPLAY_NAME,
        "state": state["state"],
        "action": state["action"],
        "model": state["model"],
        "session_start": state["session_start"],
        "updated_at": now,
        "file_kind": state["file_kind"],
    }
    beacon.update(load_window(now))
    return beacon


def process_payload(payload, now=None):
    """Die Funktion ist separat, damit Tests ohne private Hook-Daten auskommen."""
    if not isinstance(payload, dict):
        return False
    current_time = int(time.time()) if now is None else int(now)
    beacon_path, state_path = beacon_paths()
    previous = normalized_previous(load_state(state_path))
    desired = event_state(payload, previous, current_time)
    if desired is None:
        return False

    changed = any(desired[key] != previous[key] for key in
                  ("state", "action", "model", "session_start", "file_kind"))
    last_update = previous.get("updated_at")
    heartbeat_due = (last_update is None or
                     current_time - last_update >= HEARTBEAT_SECONDS)
    if changed or heartbeat_due:
        beacon = beacon_from_state(desired, current_time)
        atomic_json(beacon_path, beacon)
        desired["updated_at"] = current_time
    else:
        desired["updated_at"] = last_update
    atomic_json(state_path, desired)
    return changed or heartbeat_due


def main():
    try:
        payload = json.load(sys.stdin)
        process_payload(payload)
    except Exception:
        # Presence-Fehler duerfen den Codex-Turn niemals beeinflussen.
        pass
    try:
        # Ein leeres JSON-Objekt ist auch fuer Stop ein gueltiges Hook-Ergebnis.
        sys.stdout.write("{}\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
