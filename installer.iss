#define MyAppName      "ITD Docs Downloader"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Deepak Bholusaria"
#define MyAppExeName   "TaxDownloader.exe"
#define MyAppDataDir   "{localappdata}\ITDDocsDownloader"

[Setup]
AppId={{A3F2C1D4-8B7E-4F9A-BC12-3E5D6F7A8C90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Compatible with Inno Setup 6 and 7
AppPublisherURL=https://github.com/dkbholusaria/ITD-docs-downloader
AppSupportURL=https://github.com/dkbholusaria/ITD-docs-downloader/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=ITDDocsDownloader_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
; Minimum Windows 10
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Main executable — built by PyInstaller into dist\
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Seed assessment_years.json into AppData on first install
Source: "assessment_years.json"; DestDir: "{#MyAppDataDir}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove app data folder on uninstall only if user confirms (leave vault intact by default)
; Users who want to wipe data can delete %LOCALAPPDATA%\ITDDocsDownloader manually
