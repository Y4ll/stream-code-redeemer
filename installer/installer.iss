; ─────────────────────────────────────────────────────────────
; Inno Setup Script — Stream Code Redeemer Bot
; Genera: StreamCodeRedeemerSetup.exe
; ─────────────────────────────────────────────────────────────

#define MyAppName      "Stream Code Redeemer"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Y4ll"
#define MyAppURL       "https://github.com/Y4ll/stream-code-redeemer"
#define MyAppExeName   "StreamCodeRedeemer.exe"
#define BuildDir       "..\dist\StreamCodeRedeemer"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist\installer
OutputBaseFilename=StreamCodeRedeemerSetup
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Todos los archivos generados por PyInstaller
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Archivo de ejemplo de configuración
Source: "..\.env.example"; DestDir: "{app}"; DestName: ".env.example"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar";            Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Abrir README después de instalar
Filename: "{app}\README.md"; Description: "Ver instrucciones"; Flags: postinstall shellexec skipifsilent unchecked

[Code]
// Verificar si .env existe; si no, copiar .env.example como .env
procedure CurStepChanged(CurStep: TSetupStep);
var
  envPath, examplePath: String;
begin
  if CurStep = ssPostInstall then
  begin
    envPath     := ExpandConstant('{app}\.env');
    examplePath := ExpandConstant('{app}\.env.example');
    if not FileExists(envPath) then
      FileCopy(examplePath, envPath, False);
  end;
end;
