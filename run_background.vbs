Set WshShell = CreateObject("WScript.Shell")
strCurDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir
WshShell.Run "cmd.exe /c """ & strCurDir & "\run_worker_daemon.bat""", 0, False
