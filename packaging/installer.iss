; Script generated for Inno Setup 6.0+
; BEL (Behavioral Executive Logic) V1 Golden Windows Installer

#define MyAppName "BEL"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Google Antigravity & BEL Engineering"
#define MyAppURL "https://github.com/avyansh-bel/sight"
#define MyAppExeName "Launch_BEL.bat"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
AppId={{D37E84B1-6523-441A-97C5-C38BEA7E6281}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputBaseFilename=BEL_Setup_v1.0.0
OutputDir=..\dist
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Launch BEL automatically when Windows starts"; GroupDescription: "System Startup:"; Flags: unchecked

[Files]
Source: "..\dist\BEL_V1_Portable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: shellexec postinstall nowait skipifsilent
