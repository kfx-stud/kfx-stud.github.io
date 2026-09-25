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

echo Отправка на GitHub...
git push

echo.
echo Все изменения отправлены на GitHub!
echo Сайт обновится через 30-60 секунд.
echo.
pause