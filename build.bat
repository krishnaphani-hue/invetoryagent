@echo off
rem Builds InventoryAgent.exe with MSVC (run from any prompt).
set "VSW=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq delims=" %%i in (`"%VSW%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS=%%i"
if not defined VS (echo MSVC Build Tools not found & exit /b 1)
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
set "PG=C:\Program Files\PostgreSQL\16"
if not exist out mkdir out
cl /nologo /std:c++17 /O2 /EHsc /MT /utf-8 /W3 /I"%PG%\include" main.cpp /Fe:out\InventoryAgent.exe /Fo:out\ ^
   /link /LIBPATH:"%PG%\lib" libpq.lib advapi32.lib iphlpapi.lib ws2_32.lib version.lib user32.lib shell32.lib /SUBSYSTEM:WINDOWS /ENTRY:wmainCRTStartup /MANIFEST:EMBED /MANIFESTINPUT:InventoryAgent.manifest || exit /b 1
copy /y config.ini out\config.ini >nul
rem libpq.dll and its dependencies must sit beside the exe
for %%f in (libpq.dll libssl-3-x64.dll libcrypto-3-x64.dll libintl-9.dll libiconv-2.dll libwinpthread-1.dll zlib1.dll) do (
  if exist "%PG%\bin\%%f" copy /y "%PG%\bin\%%f" out\ >nul
)
echo Built out\InventoryAgent.exe
