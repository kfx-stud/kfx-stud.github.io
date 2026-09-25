@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo Проверка изменений...
git status -s

echo.
set /p msg="Введи описание коммита (или нажми Enter для дефолтного): "
if "%msg%"=="" set msg=Ручное обновление сайта

echo.
echo Добавление файлов в Git...
git add .

echo Создание коммита...
git commit -m "%msg%"

echo Подтягивание изменений с GitHub...
git pull --rebase origin main

echo Отправка на GitHub...
git push origin main

echo.
echo Все изменения отправлены на GitHub!
echo.
pause