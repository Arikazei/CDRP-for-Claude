' Stiller Token-Refresh: ruft Claude Code unsichtbar auf, damit der
' OAuth-Token frisch bleibt. Nur noetig, wenn in der Konfiguration
' token_status.enabled auf true steht - siehe Warnhinweis in der README.
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

home = WshShell.ExpandEnvironmentStrings("%USERPROFILE%")
candidates = Array( _
  home & "\.local\bin\claude.exe", _
  home & "\AppData\Local\Programs\claude\claude.exe", _
  "claude.exe")

For Each candidate In candidates
  If candidate = "claude.exe" Or fso.FileExists(candidate) Then
    WshShell.Run """" & candidate & """ -p ""ok""", 0, False
    WScript.Quit 0
  End If
Next
