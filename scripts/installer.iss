#define MyAppName      "AayDocCapio"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Deepak Bholusaria"
#define MyAppExeName   "AayDocCapio.exe"
#define MyAppDataDir   "{localappdata}\AayDocCapio"

[Setup]
AppId={{A3F2C1D4-8B7E-4F9A-BC12-3E5D6F7A8C90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Compatible with Inno Setup 6 and 7
AppPublisherURL=https://github.com/dkbholusaria/AayDocCapio
AppSupportURL=https://github.com/dkbholusaria/AayDocCapio/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
SourceDir=..
OutputDir=installer_output
OutputBaseFilename=AayDocCapio_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Keep installer on screen during Chromium download
DisableFinishedPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; All compiled app files from Nuitka one-dir build
Source: "dist\AayDocCapio\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; \
    BeforeInstall: SetStep('Copying application files...')

; Seed assessment_years.json to AppData (only if not already there)
Source: "assessment_years.json"; DestDir: "{#MyAppDataDir}"; \
    Flags: onlyifdoesntexist uninsneveruninstall; \
    BeforeInstall: SetStep('Setting up configuration files...')

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Launch app after install (user can untick)
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Launch {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[Code]
var
  StatusLabel : TLabel;
  SubLabel    : TLabel;

{ ------------------------------------------------------------------ }
{ Helper — update the visible status text during install             }
{ ------------------------------------------------------------------ }
procedure SetStep(Msg: String);
begin
  if Assigned(StatusLabel) then
  begin
    StatusLabel.Caption := Msg;
    StatusLabel.Update;
  end;
end;

procedure SetSub(Msg: String);
begin
  if Assigned(SubLabel) then
  begin
    SubLabel.Caption := Msg;
    SubLabel.Update;
  end;
end;

{ ------------------------------------------------------------------ }
{ Add custom labels to the Installing page                           }
{ ------------------------------------------------------------------ }
procedure InitializeWizard;
var
  InstallingPage : TWizardPage;
begin
  InstallingPage := PageFromID(wpInstalling);

  StatusLabel             := TLabel.Create(WizardForm);
  StatusLabel.Parent      := InstallingPage.Surface;
  StatusLabel.Left        := 0;
  StatusLabel.Top         := 8;
  StatusLabel.Width       := InstallingPage.SurfaceWidth;
  StatusLabel.Height      := 20;
  StatusLabel.Font.Style  := [fsBold];
  StatusLabel.Caption     := 'Preparing installation...';

  SubLabel                := TLabel.Create(WizardForm);
  SubLabel.Parent         := InstallingPage.Surface;
  SubLabel.Left           := 0;
  SubLabel.Top            := 30;
  SubLabel.Width          := InstallingPage.SurfaceWidth;
  SubLabel.Height         := 18;
  SubLabel.Font.Color     := $00666666;
  SubLabel.Caption        := '';
end;

{ ------------------------------------------------------------------ }
{ Run after all files are copied — install Chromium                  }
{ ------------------------------------------------------------------ }
procedure CurStepChanged(CurStep: TSetupStep);
var
  ExePath    : String;
  ResultCode : Integer;
begin
  if CurStep = ssPostInstall then
  begin
    ExePath := ExpandConstant('{app}\{#MyAppExeName}');

    { Step 1 }
    SetStep('Creating application shortcuts...');
    SetSub('Start Menu and Desktop shortcuts');
    Sleep(600);

    { Step 2 }
    SetStep('Downloading Chromium browser...');
    SetSub('This is a one-time download of ~150 MB. Please stay connected.');

    if not Exec(ExePath, '--install-browsers', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    begin
      SetStep('Warning: Chromium download failed (code ' + IntToStr(ResultCode) + ')');
      SetSub('The app will retry automatically on first launch.');
      Sleep(3000);
    end
    else
    begin
      { Step 3 }
      SetStep('Chromium installed successfully.');
      SetSub('Browser is ready — no internet required during downloads.');
      Sleep(1000);

      { Step 4 }
      SetStep('Finalising installation...');
      SetSub('Writing registry entries and cleaning up.');
      Sleep(800);

      { Done }
      SetStep('Installation complete!');
      SetSub('{#MyAppName} v{#MyAppVersion} is ready to use.');
    end;
  end;
end;
