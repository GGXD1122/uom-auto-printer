#define AppName "UOM自动打印"
#define AppVersion "1.2.56"
#define AppExeName "UOM自动打印.exe"
#define AppMutexName "Global\GeGeXD-UOM-Auto-Printer"

[Setup]
AppId={{7BD1D96D-5614-4D69-BF1E-39DA08B391F2}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion=1.2.56.0
AppPublisher=鸽鸽XD
DefaultDirName={localappdata}\Programs\UOM Auto Printer
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=UOM自动打印-Setup-v1.2.56
SetupIconFile=..\assets\app-icon.ico
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
CloseApplications=no
RestartApplications=no
AppMutex={#AppMutexName}
UsePreviousTasks=no
UsePreviousAppDir=yes
UsePreviousGroup=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "..\dist\UOMAutoPrinter\*"; DestDir: "{app}"; Excludes: "UOMAutoPrinter.exe"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\UOMAutoPrinter\UOMAutoPrinter.exe"; DestDir: "{app}"; DestName: "{#AppExeName}"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{app}\UOM实名全自动打印.exe"
Type: files; Name: "{userdesktop}\UOM实名全自动打印.lnk"
Type: filesandordirs; Name: "{userprograms}\UOM实名全自动打印"
Type: files; Name: "{app}\OUM实名全自动打印.exe"
Type: files; Name: "{userdesktop}\OUM实名全自动打印.lnk"
Type: filesandordirs; Name: "{userprograms}\OUM实名全自动打印"
Type: files; Name: "{app}\鸽鸽XD&UOM二维码自动打印.exe"
Type: files; Name: "{userdesktop}\鸽鸽XD&UOM二维码自动打印.lnk"
Type: filesandordirs; Name: "{userprograms}\鸽鸽XD&UOM二维码自动打印"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："; Flags: checkedonce

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function IsProcessRunning(const ExeName: String): Boolean;
var
  Locator, Service, Processes: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('', 'root\CIMV2');
    Processes := Service.ExecQuery(
      'SELECT * FROM Win32_Process WHERE Name="' + ExeName + '"'
    );
    Result := Processes.Count > 0;
  except
    Result := False;
  end;
end;

function LegacyWindowRunning: Boolean;
begin
  Result :=
    (FindWindowByWindowName('UOM自动打印') <> 0) or
    (FindWindowByWindowName('UOM自动打印状态') <> 0);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if CheckForMutexes('{#AppMutexName}') or
     LegacyWindowRunning or
     IsProcessRunning('{#AppExeName}') then
  begin
    MsgBox(
      '检测到 UOM自动打印 正在运行。' + #13#10 + #13#10 +
      '请先在右下角托盘图标中选择“退出程序”，关闭软件后再重新运行安装包。',
      mbInformation,
      MB_OK
    );
    Result := False;
  end;
end;
