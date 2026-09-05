@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PRODUCT_NAME=UOM自动打印"
set "VERSION=1.2.56"
rem Wine 的 cmd 代码页会破坏 PyInstaller 的中文 --name。
rem 构建目录和内部 EXE 使用稳定的 ASCII 名称，安装时再恢复中文产品名。
set "PRODUCT_BUILD_NAME=UOMAutoPrinter"
set "PRODUCT_EXE=dist\%PRODUCT_BUILD_NAME%\%PRODUCT_BUILD_NAME%.exe"
set "SETUP_EXE=release\UOM自动打印-Setup-v%VERSION%.exe"
set "PYTHON_EXE=py"
set "PYTHON_ARGS=-3.11"
if exist "C:\Python311\python.exe" (
  set "PYTHON_EXE=C:\Python311\python.exe"
  set "PYTHON_ARGS="
)

set "BUILD_PYTHON=.venv-win\Scripts\python.exe"
if not exist "%BUILD_PYTHON%" (
  "%PYTHON_EXE%" %PYTHON_ARGS% --version >nul 2>nul
  if errorlevel 1 call :install_python
  if errorlevel 1 goto :failed
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv .venv-win
  if errorlevel 1 (
    echo [提示] 当前构建环境不含 venv，改用现有 Python 3.11 环境。
    set "BUILD_PYTHON=%PYTHON_EXE%"
  )
)
if exist ".venv-win\Scripts\python.exe" set "BUILD_PYTHON=.venv-win\Scripts\python.exe"
"%BUILD_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :failed
rem Wine/Windows may encode editable .pth paths as cp1252.  A regular local
rem install avoids embedding the Chinese checkout path and is equally valid
rem for the subsequent --paths src PyInstaller build.
"%BUILD_PYTHON%" -m pip install --no-build-isolation ".[windows,build,test]"
if errorlevel 1 goto :failed
"%BUILD_PYTHON%" -m pytest -q
if errorlevel 1 goto :failed
"%BUILD_PYTHON%" scripts\generate_icon.py
if errorlevel 1 goto :failed

"%BUILD_PYTHON%" -m PyInstaller --noconfirm --clean --windowed --onedir --noupx ^
  --name "%PRODUCT_BUILD_NAME%" ^
  --icon "assets\app-icon.ico" ^
  --version-file "windows\version_info.txt" ^
  --add-data "assets\app-icon.png;assets" ^
  --add-data "assets\gegexd-avatar.jpg;assets" ^
  --add-data "assets\uom-qr-logo.png;assets" ^
  --paths "src" ^
  --hidden-import PySide6.QtWebEngineCore ^
  --hidden-import PySide6.QtWebEngineWidgets ^
  --hidden-import PySide6.QtPrintSupport ^
  --exclude-module cv2 ^
  --exclude-module numpy ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtQuickWidgets ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtOpenGL ^
  --exclude-module PySide6.QtPositioning ^
  --exclude-module tkinter ^
  run.py
if errorlevel 1 goto :failed

"%BUILD_PYTHON%" scripts\prune_windows_bundle.py "dist\%PRODUCT_BUILD_NAME%"
if errorlevel 1 goto :failed

if defined UOM_SIGN_CERT_SHA1 (
  where signtool >nul 2>nul
  if errorlevel 1 (
    echo [警告] 已设置签名证书，但没有找到 signtool.exe，跳过签名。
  ) else (
    signtool sign /sha1 "%UOM_SIGN_CERT_SHA1%" /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "%PRODUCT_EXE%"
    if errorlevel 1 goto :failed
  )
) else (
  echo [提示] 当前为未签名测试版。正式发布请设置 UOM_SIGN_CERT_SHA1 后重新构建。
)

powershell -NoProfile -ExecutionPolicy Bypass -File "windows\write_checksums.ps1" -ReleaseDir "dist\%PRODUCT_BUILD_NAME%"

call :install_inno
if errorlevel 1 goto :failed
"%ISCC%" "windows\installer.iss"
if errorlevel 1 goto :failed
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (-not (Test-Path -LiteralPath '%SETUP_EXE%')) { exit 1 }"
if errorlevel 1 (
  echo [错误] 安装包构建完成后未找到预期文件：%SETUP_EXE%
  goto :failed
)
if defined UOM_SIGN_CERT_SHA1 (
  signtool sign /sha1 "%UOM_SIGN_CERT_SHA1%" /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "%SETUP_EXE%"
  if errorlevel 1 goto :failed
)
"%BUILD_PYTHON%" scripts\write_installer_checksum.py --release-dir "release" --version "%VERSION%"
if errorlevel 1 goto :failed

echo.
echo Windows 一键安装包构建完成："%SETUP_EXE%"
echo 以后只需要分发 release 文件夹中的这个 Setup.exe。
echo 内部使用 onedir、无UPX、无混淆；建议正式发布前完成可信代码签名。
pause
exit /b 0

:install_python
echo [准备环境] 没有检测到 Python 3.11，正在安装官方 Python 3.11 x64...
where winget >nul 2>nul
if not errorlevel 1 (
  winget install --id Python.Python.3.11 -e --scope user --accept-package-agreements --accept-source-agreements
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\python-3.11.9-amd64.exe'"
  if errorlevel 1 exit /b 1
  start /wait "" "%TEMP%\python-3.11.9-amd64.exe" /quiet InstallAllUsers=0 Include_launcher=1 PrependPath=1 Include_test=0
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
  set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  set "PYTHON_ARGS="
  exit /b 0
)
py -3.11 --version >nul 2>nul
if errorlevel 1 (
  echo [错误] Python 3.11 安装后仍未找到，请重启电脑后再次运行本脚本。
  exit /b 1
)
exit /b 0

:find_inno
set "ISCC="
if exist "C:\InnoSetup6\ISCC.exe" set "ISCC=C:\InnoSetup6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC exit /b 0
exit /b 1

:install_inno
call :find_inno
if not errorlevel 1 exit /b 0
echo [准备环境] 没有检测到 Inno Setup 6，正在安装官方安装包生成器...
where winget >nul 2>nul
if not errorlevel 1 (
  winget install --id JRSoftware.InnoSetup -e --scope user --accept-package-agreements --accept-source-agreements
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing 'https://jrsoftware.org/download.php/is.exe' -OutFile '%TEMP%\innosetup-6.exe'"
  if errorlevel 1 exit /b 1
  start /wait "" "%TEMP%\innosetup-6.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER
)
call :find_inno
if errorlevel 1 (
  echo [错误] Inno Setup 安装后仍未找到，无法生成一键安装包。
  exit /b 1
)
exit /b 0

:failed
echo.
echo 构建失败，请查看上方错误。
pause
exit /b 1
