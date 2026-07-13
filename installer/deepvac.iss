; Inno Setup script for DeepVac Insight.
;
; Prereqs:
;   1. Build the app first:  pyinstaller deepvac.spec   (from the repo root)
;      This produces dist\DeepVac\DeepVac.exe and everything it needs.
;   2. Install Inno Setup (https://jrsoftware.org/isinfo.php, or
;      `winget install JRSoftware.InnoSetup`) if it isn't already.
;   3. Compile this script:  iscc installer\deepvac.iss   (from the repo root)
;      Output: installer\output\DeepVacInsight-Setup-<version>.exe
;
; What this installs: the onedir build from dist\DeepVac\ into Program
; Files, plus a Start Menu shortcut, an optional Desktop shortcut, and a
; standard uninstaller. It deliberately does NOT touch
; %LOCALAPPDATA%\DeepVac\data (databases/logs/backups/reports) -- that's
; created by the app itself on first run and is left alone by the
; uninstaller too, so uninstalling never deletes user data.

#define MyAppName "DeepVac Insight"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "DeepVac"
#define MyAppExeName "DeepVac.exe"

[Setup]
AppId={{6E2B7B7B-6B9E-4B7A-9C3A-6C7C3B7B0C1D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=DeepVacInsight-Setup-{#MyAppVersion}
SetupIconFile=..\resources\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Program Files needs elevation; user data lives in %LOCALAPPDATA% instead
; (see app/common.py), so this is the only part of the app that needs admin.
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\DeepVac\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
