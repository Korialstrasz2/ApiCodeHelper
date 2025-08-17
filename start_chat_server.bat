@echo off
setlocal enabledelayedexpansion

set PORT=8000

:find_port
netstat -ano | findstr ":%PORT% " >nul
if %ERRORLEVEL%==0 (
    echo Port %PORT% in use. Trying next port...
    set /a PORT+=1
    goto find_port
)

echo Starting server on port %PORT% ...
start "" python manage.py runserver %PORT%

REM Give the server a moment to start
timeout /t 5 /nobreak >nul

start "" http://127.0.0.1:%PORT%/chat/

endlocal
