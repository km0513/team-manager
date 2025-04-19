@echo off
setlocal enabledelayedexpansion

echo ================================
echo 🚀 Heroku Smart Deploy Script
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

echo 🟢 Adding all code and template files...
git add *.py
if exist templates\*.html git add templates\*.html
if exist static\*.js git add static\*.js
if exist static\*.css git add static\*.css
git add *.bat

echo 🟡 Committing (will skip if nothing to commit)...
git commit -m "%commitMsg%" || echo (No changes to commit.)

echo ⬆️ Pushing to Heroku...
git push heroku main

echo ✅ Deployment to Heroku complete.
goto end

:end
pause