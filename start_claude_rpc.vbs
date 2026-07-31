' Startet claude_rpc.py unsichtbar im Hintergrund (kein Konsolenfenster).
'
' Gestartet wird eine umbenannte Kopie von pythonw.exe, damit der Prozess im
' Task-Manager als "ClaudeDiscordPresence" auftaucht und nicht als eines von
' mehreren "pythonw.exe". setup_venv.bat legt die Kopie an.
'
' Bewusst NICHT das Microsoft-Store-Python: dort ist %APPDATA% umgeleitet,
' der Ordner %APPDATA%\Claude bleibt unsichtbar und alle Datei-Leser stumm.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
py = base & "\.venv\Scripts\ClaudeDiscordPresence.exe"
If Not fso.FileExists(py) Then py = base & "\.venv\Scripts\pythonw.exe"
script = base & "\claude_rpc.py"
If Not fso.FileExists(py) Then
  MsgBox "Virtuelle Umgebung fehlt. Bitte zuerst setup_venv.bat ausfuehren.", 48, "claude_rpc"
  WScript.Quit 1
End If
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """" & py & """ """ & script & """", 0, False
