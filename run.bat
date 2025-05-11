@echo off
cd D:\team_manager
call venv\Scripts\activate

:: Start Flask app in a new background terminal
start cmd /k "python app.py"

:: Wait briefly to ensure the server starts
timeout /t 2 /nobreak >nul

:: Open the browser to the app
start http://127.0.0.1:5001

exit
