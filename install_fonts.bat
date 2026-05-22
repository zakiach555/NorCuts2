@echo off
echo ==========================================
echo Installing Arabic Fonts for NorCuts
echo ==========================================
echo.

:: Create the font cache directory
echo Creating font cache directory...
if not exist "C:\vcfonts" (
    mkdir "C:\vcfonts"
    echo Created C:\vcfonts directory
) else (
    echo C:\vcfonts directory already exists
)

:: Copy fonts from arabic font folder
echo.
echo Copying Arabic fonts...
if exist "arabic font\" (
    copy /Y "arabic font\*.otf" "C:\vcfonts\" >nul
    copy /Y "arabic font\*.ttf" "C:\vcfonts\" >nul
    echo Fonts copied successfully!
) else (
    echo ERROR: 'arabic font' folder not found!
    echo Please make sure you're running this from the NorCuts directory.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo Font installation complete!
echo ==========================================
echo.
echo The following fonts have been installed to C:\vcfonts:
dir /b "C:\vcfonts\*.otf" 2>nul
dir /b "C:\vcfonts\*.ttf" 2>nul
echo.
echo You can now use NorCuts with proper Arabic subtitle rendering.
echo.
pause
