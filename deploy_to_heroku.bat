@echo off
setlocal enabledelayedexpansion

echo ================================
echo 🚀 Heroku Deployment Script
echo ================================
echo.

:: Ask for commit message
set /p commitMsg=Enter your commit message: 

if "%commitMsg%"=="" (
    echo ❌ Commit message cannot be empty.
    goto end
)

echo 🔄 Pulling latest code...
git pull

echo 🟢 Adding and committing...
git add .
git commit -m "%commitMsg%"

echo ⬆️ Pushing to Heroku...
git push heroku main

echo ✅ Deployment to Heroku complete.
goto end

:end
pause