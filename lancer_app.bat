@echo off
title Portail Investissement — Serveur Local
cd /d "%~dp0"

:: Vérifier que Python est disponible
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou introuvable dans le PATH.
    pause
    exit /b 1
)

:: Télécharger les dépendances locales si pas encore fait
if not exist "libs\chart.umd.min.js" (
    echo  Premiere utilisation : telechargement des dependances...
    python setup_local.py
    echo.
)

echo.
echo  ══════════════════════════════════════════
echo   Portail Investissement — Serveur Local
echo  ══════════════════════════════════════════
echo   Adresse : http://localhost:8080
echo   Pour arreter le serveur : Ctrl+C
echo  ══════════════════════════════════════════
echo.

:: Ouvrir le navigateur après 1 seconde
start "" /b cmd /c "timeout /t 1 /nobreak >nul && start http://localhost:8080/index.html"

:: Lancer le serveur
python -m http.server 8080
