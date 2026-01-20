$DesktopPath = [Environment]::GetFolderPath("Desktop")
$WshShell = New-Object -ComObject WScript.Shell

# Create HVAC GUI shortcut
$GUIShortcutPath = Join-Path $DesktopPath "HVAC Robot Controller.lnk"
$GUIShortcut = $WshShell.CreateShortcut($GUIShortcutPath)
$GUIShortcut.TargetPath = "C:\dev\ExoBot\exo\launch_gui.bat"
$GUIShortcut.WorkingDirectory = "C:\dev\ExoBot\exo"
$GUIShortcut.Description = "Launch HVAC Robot Controller GUI"
$GUIShortcut.Save()
Write-Host "Created: $GUIShortcutPath"

# Create Open Repo shortcut
$RepoShortcutPath = Join-Path $DesktopPath "ExoBot Repo.lnk"
$RepoShortcut = $WshShell.CreateShortcut($RepoShortcutPath)
$RepoShortcut.TargetPath = "C:\dev\ExoBot\exo\open_repo.bat"
$RepoShortcut.WorkingDirectory = "C:\dev\ExoBot\exo"
$RepoShortcut.Description = "Open ExoBot repo in VS Code"
$RepoShortcut.Save()
Write-Host "Created: $RepoShortcutPath"

Write-Host ""
Write-Host "Desktop shortcuts created successfully!"
