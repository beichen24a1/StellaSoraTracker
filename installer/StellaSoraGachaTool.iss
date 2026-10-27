#define MyAppName "星塔旅人数据工具"
#define MyAppVersion "1.3.1"
#define MyAppExeName "StellaSoraGachaTool.exe"
#define MyLauncherName "启动器.exe"

#ifndef MySourceDir
  #define MySourceDir "..\release\github\StellaSoraGachaTool"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\release"
#endif
#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "StellaSoraGachaTool-Setup-1.3.1"
#endif

[Setup]
AppId={{B8E6C27A-53CE-47F7-9EA7-4383B5C56E63}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=StellaSoraTracker contributors
AppPublisherURL=https://github.com/beichen24a1/StellaSoraTracker
DefaultDirName={localappdata}\StellaSoraGachaTool
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\app_icon.ico
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion=1.3.1.0
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} 安装程序

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; Subkey: "Software\StellaSoraGachaTool"; ValueType: string; ValueName: "InstallLocation"; ValueData: "{app}"; Flags: uninsdeletekey

[Icons]
; 普通模式启动器：不请求管理员权限，读取游戏时由客户端按需提权重启
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyLauncherName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyLauncherName}"; WorkingDir: "{app}"; Tasks: desktopicon
