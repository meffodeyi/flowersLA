@echo off
where py >nul 2>nul
if errorlevel 1 (
    python "%~dp0play.py"
) else (
    py "%~dp0play.py"
)
pause >nul
