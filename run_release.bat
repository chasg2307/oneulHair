@echo off
setlocal
cd /d "%~dp0"

set "EXE_PATH="
set "CONF_PATH=%~dp0oneulhair.conf"

for /d %%D in ("%~dp0*") do (
  if exist "%%~fD\*.exe" (
    for %%E in ("%%~fD\*.exe") do (
      set "EXE_PATH=%%~fE"
      goto :exe_found
    )
  )
)

:exe_found
if not defined EXE_PATH (
  echo [ERROR] Executable not found under release folder.
  echo Run build_onedir.ps1 first.
  pause
  exit /b 1
)

if not exist "%CONF_PATH%" (
  echo [ERROR] Config file not found: %CONF_PATH%
  echo Copy and edit oneulhair.conf before running.
  pause
  exit /b 1
)

set "ONEUL_CONF_PATH=%CONF_PATH%"

"%EXE_PATH%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Process exited with code %EXIT_CODE%.
  pause
)

exit /b %EXIT_CODE%
