@echo off
REM Double-click or run this in Command Prompt to set up the MTG skill.
REM It just finds Python and hands off to setup.py.

where py >nul 2>nul
if %errorlevel%==0 (
    py "%~dp0setup.py"
    goto done
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0setup.py"
    goto done
)

echo Could not find Python. Install Python 3.10+ from https://python.org
echo Make sure to tick "Add Python to PATH" during install, then run this again.
pause

:done
