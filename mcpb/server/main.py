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
SERVER_INFO = {"name": "claude-discord-presence", "version": "1.0.0"}


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "ClaudeDiscordPresence")
    os.makedirs(path, exist_ok=True)
    return path


def env_flag(name, default=False):
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "ja")


def env_int(name, default):
    try:
        return int((os.environ.get(name) or "").strip())
    except ValueError:
        return default


def build_config():
    """Vorlage + Benutzereinstellungen aus dem Manifest zu config.json."""
    with open(os.path.join(HERE, "config.default.json"), encoding="utf-8") as handle:
        cfg = json.load(handle)

    client_id = (os.environ.get("CLAUDE_RPC_CLIENT_ID") or "").strip()
    if client_id:
        cfg["client_id"] = client_id

    cfg["idle_timeout_minutes"] = env_int("CLAUDE_RPC_IDLE_MINUTES", 25)

    use_api = env_flag("CLAUDE_RPC_USE_API", False)
    cfg.setdefault("token_status", {})["enabled"] = use_api
    plan = (os.environ.get("CLAUDE_RPC_PLAN") or "").strip()
    cfg["token_status"]["plan_override"] = plan
    cfg["token_status"]["show_plan"] = bool(plan) or use_api

    idle = (os.environ.get("CLAUDE_RPC_IDLE_TEXT") or "").strip()
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
        state = dict(rpc.LAST_STATE)
        if not state:
            return "Noch keine Presence gesendet (Claude Desktop nicht aktiv?)."
        state["paused"] = rpc.is_paused()
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


def main():
    os.environ["CLAUDE_RPC_CONFIG"] = build_config()
    os.environ["CLAUDE_RPC_DATA_DIR"] = data_dir()

    import claude_rpc as rpc

    threading.Thread(target=rpc.main, name="presence", daemon=True).start()

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


if __name__ == "__main__":
    main()
