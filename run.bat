@echo off
rem Starts everything from this folder (downloads portable tools on the first run). Stop with stop.bat.
rem Options: run.bat -NoBrowser   -SkipAgent
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
