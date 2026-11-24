F99th LiveOps - Manual Desktop Launcher
======================================
Target system: F99th3 (Windows)
Expected app: C:\F99th\Dashboard\app.py

1. Extract ALL files from this ZIP to a temporary folder on F99th3.
2. Right-click Install-F99thLiveOpsShortcut.ps1 and select Run with PowerShell.
   If Windows policy blocks this option, open PowerShell in the extracted folder and run:
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-F99thLiveOpsShortcut.ps1
3. The installer creates the desktop shortcut: F99th LiveOps Map.
4. Double-click the shortcut. Leave its PowerShell console window open while using the dashboard.
5. Open http://127.0.0.1:8765 to check the map. Your existing Tailscale Funnel
   configuration is not modified by this launcher.

Behavior:
- Uses C:\F99th\Dashboard\.venv\Scripts\python.exe if present; otherwise checks installed Python.
- If port 8765 already has a listener, the launcher does NOT create a second server.
- The console shows Python output and startup errors.
- No scheduled tasks, Windows Startup items, firewall rules, or Discord permissions are changed.
- Closing the console or pressing Ctrl+C stops the manually launched map.
- Future ServerBot remote automation will need a separate managed/background launch approach.

Security: Use only on the F99th3 host. Do not expose port 8765 via router forwarding.
