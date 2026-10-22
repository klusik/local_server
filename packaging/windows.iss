; Inno Setup 7. Build-time values are supplied by tools/build_windows.py.
#if VER < EncodeVer(7, 0, 0)
  #error Inno Setup 7 or newer is required.
#endif

[Setup]
AppId={{EC96AF94-6E9A-40F1-8F48-3EF16AE4A803}
AppName=Local Server
AppVersion={#AppVersion}
AppPublisher=Rudolf Klusal
DefaultDirName={localappdata}\Programs\LocalServer
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LocalServer.exe
CloseApplications=yes
CloseApplicationsFilter=LocalServer.exe
RestartApplications=no
SetupLogging=yes

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "LocalServer.exe"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Local Server"; Filename: "{app}\LocalServer.exe"; WorkingDir: "{app}"

; No wildcard uninstall deletion: packages, projects and database data are retained.
