# T+0 Monitor - Start Script (Silent)
$scriptPath = Join-Path $PSScriptRoot "t0_monitor.py"
$pythonExe = "C:\Users\Ryan\AppData\Local\Programs\Python\Python313\python.exe"

# Start monitor
Start-Process -FilePath $pythonExe -ArgumentList $scriptPath -WindowStyle Hidden
