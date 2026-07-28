' Startet claude_rpc.py unsichtbar im Hintergrund (kein Konsolenfenster).
' Nutzt bewusst das venv-Python, NICHT das Microsoft-Store-Python:
' Store-Apps bekommen ein umgeleitetes %APPDATA%, dadurch sieht das Skript
' den Ordner %APPDATA%\Claude nicht und alle lokalen Reader bleiben leer.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
py = base & "\.venv\Scripts\pythonw.exe"
script = base & "\claude_rpc.py"
If Not fso.FileExists(py) Then
  MsgBox "Virtuelle Umgebung fehlt. Bitte zuerst setup_venv.bat ausfuehren.", 48, "claude_rpc"
  WScript.Quit 1
End If
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """" & py & """ """ & script & """", 0, False
