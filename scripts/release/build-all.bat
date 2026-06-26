@echo off
REM Main release build on Windows. Copy release.env.example to release.env first.
setlocal
chcp 65001 >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-all.ps1" %*
exit /b %ERRORLEVEL%
