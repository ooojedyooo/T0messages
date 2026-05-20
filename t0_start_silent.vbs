' T+0盯盘 - 静默启动器
' 通过VBScript启动Python脚本，完全不弹黑框窗口
' Python脚本自身负责：PID管理、防重复启动、交易日判断

Dim objShell, objFSO, scriptDir, pythonExe, pythonScript

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' 路径
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
pythonExe = "C:\Users\Ryan\AppData\Local\Programs\Python\Python313\python.exe"
pythonScript = objFSO.BuildPath(scriptDir, "t0_monitor.py")

' 静默启动：0=隐藏窗口, False=不等待完成
objShell.Run """" & pythonExe & """ """ & pythonScript & """", 0, False
