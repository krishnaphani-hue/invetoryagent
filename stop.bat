@echo off
rem Stops the server, the agent and the PostgreSQL started by run.bat.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Stop
