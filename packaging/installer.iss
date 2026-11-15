; Inno Setup recipe for the Windows installer. Build with:  iscc /DVersion=0.1.0 packaging\installer.iss
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6B0E2D2C-0C57-4B76-9E3A-6C3C0E5B7A11}
AppName=MiniBook Studio
AppVersion={#Version}
AppPublisher=Wizardblock
AppPublisherURL=https://github.com/Wizardblock/Minibook-Studio
DefaultDirName={autopf}\MiniBook Studio
DefaultGroupName=MiniBook Studio
OutputDir=..\release
OutputBaseFilename=MiniBook-Studio-Setup-{#Version}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\MiniBookStudio.exe
LicenseFile=..\LICENSE
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\MiniBookStudio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\samples\*"; DestDir: "{app}\samples"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\MiniBook Studio"; Filename: "{app}\MiniBookStudio.exe"
Name: "{group}\Sample books (CSV)"; Filename: "{app}\samples"
Name: "{autodesktop}\MiniBook Studio"; Filename: "{app}\MiniBookStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MiniBookStudio.exe"; Description: "Start MiniBook Studio"; Flags: nowait postinstall skipifsilent
