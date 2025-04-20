@echo off
cd /d D:\team_manager

:: Start Flask app in a new background terminal and activate venv there
start cmd /k "call venv\Scripts\activate && python app.py"

:: Wait briefly to ensure the server starts
timeout /t 2 /nobreak >nul

:: Open the browser to the app
start http://127.0.0.1:5000

exit
