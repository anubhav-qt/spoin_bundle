Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
ps1Path = objFSO.BuildPath(scriptDir, "backup_to_neon.ps1")

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1Path & """ -Quiet"
exitCode = objShell.Run(cmd, 0, True)

WScript.Quit exitCode
