"""MCP-Server fuer die Claude-Discord-Presence.

Bewusst ohne SDK: die offizielle mcp-Bibliothek zieht pydantic nach, das
eine kompilierte Rust-Erweiterung mitbringt. Das Bundle soll aber keine
fremden Binaerdateien enthalten, damit weder eine Signatur noetig ist noch
Virenscanner anschlagen. Das hier ist reines JSON-RPC ueber stdio.

Der Server startet mit der Claude-Desktop-App und stirbt mit ihr -- das
ersetzt den Autostart-Eintrag im Startmenue.
"""
import json
import os
import sys
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, HERE)

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "claude-discord-presence", "version": "1.2.0"}


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "ClaudeDiscordPresence")
    os.makedirs(path, exist_ok=True)
    return path


def env_str(name):
    """Wert einer Umgebungsvariablen, leer bei nicht ersetzten Platzhaltern.

    Claude Desktop loest "${user_config.feld}" nicht auf, wenn das Feld im
    Einstellungsdialog leer geblieben ist -- der Platzhalter kommt dann
    woertlich an. Ohne diese Pruefung ueberschreibt er die Vorgabe aus
    config.default.json mit Unsinn.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw or ("${" in raw and raw.endswith("}")):
        return ""
    return raw


def env_flag(name, default=False):
    raw = env_str(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "ja")


def env_int(name, default):
    try:
        return int(env_str(name))
    except ValueError:
        return default


def build_config():
    """Vorlage + Benutzereinstellungen aus dem Manifest zu config.json."""
    with open(os.path.join(HERE, "config.default.json"), encoding="utf-8") as handle:
        cfg = json.load(handle)

    client_id = env_str("CLAUDE_RPC_CLIENT_ID")
    if client_id:
        cfg["client_id"] = client_id

    cfg["idle_timeout_minutes"] = env_int("CLAUDE_RPC_IDLE_MINUTES", 25)
    cfg.setdefault("plan", {})["override"] = env_str("CLAUDE_RPC_PLAN")
    cfg.setdefault("ui_limits", {})["max_age_minutes"] = env_int(
        "CLAUDE_RPC_LIMIT_MAX_AGE", 180
    )

    idle = env_str("CLAUDE_RPC_IDLE_TEXT")
    if idle:
        cfg.setdefault("texts", {})["open"] = [idle]

    path = os.path.join(data_dir(), "config.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, ensure_ascii=False, indent=2)
    return path


TOOLS = [
    {
        "name": "presence_status",
        "description": (
            "Zeigt, was gerade als Discord-Rich-Presence gesendet wird: "
            "Titelzeile, Statuszeile, erkannte Aktivitaet und Auslastung."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "presence_pause",
        "description": "Entfernt die Discord-Presence, bis sie fortgesetzt wird.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "presence_resume",
        "description": "Setzt eine pausierte Discord-Presence wieder fort.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call_tool(name, rpc):
    if name == "presence_pause":
        rpc.set_paused(True)
        return "Presence pausiert."
    if name == "presence_resume":
        rpc.set_paused(False)
        return "Presence wieder aktiv."
    if name == "presence_status":
        # read_state() faellt auf die Datei des sendenden Prozesses zurueck,
        # falls dieser hier nur Werkzeugaufrufe beantwortet.
        state = dict(rpc.read_state())
        if not state:
            return ("Noch keine Presence gesendet. Sie erscheint, sobald du "
                    "im Claude-Fenster arbeitest.")
        return json.dumps(state, ensure_ascii=False, indent=2)
    raise ValueError("Unbekanntes Werkzeug: %s" % name)


def write(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(message, rpc):
    method = message.get("method")
    msg_id = message.get("id")

    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = message.get("params") or {}
        text = call_tool(params.get("name"), rpc)
        return {"content": [{"type": "text", "text": text}]}
    if msg_id is None:
        return None
    raise ValueError("Unbekannte Methode: %s" % method)


def serve_stdio(rpc):
    """JSON-RPC ueber stdin/stdout bedienen.

    Laeuft im Nebenfaden, weil der Hauptfaden der Presence-Schleife gehoert.
    Schliesst Claude Desktop die Leitung, endet der Prozess -- sonst liefe
    die Schleife weiter, obwohl niemand mehr zuhoert.
    """
    try:
        _serve(rpc)
    finally:
        sys.stderr.flush()
        os._exit(0)


def _serve(rpc):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        msg_id = message.get("id")
        try:
            result = handle(message, rpc)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            if msg_id is not None:
                write({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32000, "message": str(exc)},
                })
            continue
        if msg_id is not None and result is not None:
            write({"jsonrpc": "2.0", "id": msg_id, "result": result})


def main():
    os.environ["CLAUDE_RPC_CONFIG"] = build_config()
    os.environ["CLAUDE_RPC_DATA_DIR"] = data_dir()

    import claude_rpc as rpc

    # Die Presence-Schleife gehoert in den Hauptfaden: uiautomation braucht
    # dort das initialisierte COM, und pypresence seine Ereignisschleife.
    # Andersherum verbindet sich pypresence noch, bleibt dann aber im ersten
    # update() haengen -- ohne Fehlermeldung, der Prozess lebt einfach weiter.
    threading.Thread(target=serve_stdio, args=(rpc,), name="mcp", daemon=True).start()
    try:
        rpc.main()
    except Exception:
        traceback.print_exc(file=sys.stderr)
    # Kehrt zurueck, wenn schon eine Instanz sendet: dann nur noch bedienen.
    threading.Event().wait()


if __name__ == "__main__":
    main()
