@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-extension.ps1" %*
exit /b %ERRORLEVEL%
