@echo off
cd /d e:\project\NextWeb
mkdir config\scrape-meta 2>nul
if exist apps\scrape\data\meta\site-mirrors.json copy /Y apps\scrape\data\meta\site-mirrors.json config\scrape-meta\ >nul
if exist apps\scrape\data\meta\iqqtv-mirror.json copy /Y apps\scrape\data\meta\iqqtv-mirror.json config\scrape-meta\ >nul
if exist apps\scrape\data\meta\airav-mirror.json copy /Y apps\scrape\data\meta\airav-mirror.json config\scrape-meta\ >nul
echo exported to config\scrape-meta:
dir /b config\scrape-meta
