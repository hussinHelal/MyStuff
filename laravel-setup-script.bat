@echo off
setlocal EnableDelayedExpansion

echo Laravel Project Setup Script
echo ===========================
echo.

:: Get project name
set /p project_name=Enter your project name: 

:: Create Laravel project
echo.
echo Creating Laravel project: %project_name%
echo.
call composer create-project --prefer-dist laravel/laravel %project_name%

:: Check if project creation was successful
if not exist "%project_name%\" (
    echo.
    echo ERROR: Project creation failed!
    echo.
    pause
    exit /b 1
)

:: Change to project directory
cd %project_name%

:: Verify we're in the project directory
if not exist "artisan" (
    echo.
    echo ERROR: Could not find artisan file, something went wrong.
    echo.
    cd ..
    pause
    exit /b 1
)

:: Run npm install
echo.
echo Running npm install...
call npm install

:: Run npm run build
echo.
echo Running npm run build...
call npm run build

:: Ask about API
echo.
set /p install_api=Do you want to install API features? (y/n): 

:: Ask about JWT
echo.
set /p install_jwt=Do you want to install JWT authentication? (y/n): 

:: Install JWT if requested
if /i "%install_jwt%"=="y" (
    echo.
    echo Installing JWT authentication...
    call composer require tymon/jwt-auth
    
    echo.
    echo Publishing JWT configuration...
    call php artisan vendor:publish --provider="Tymon\JWTAuth\Providers\LaravelServiceProvider"
    
    echo.
    echo Generating JWT secret...
    call php artisan jwt:secret
)

:: Configure API if requested
if /i "%install_api%"=="y" (
    echo.
    echo Setting up API features...
    :: Create API routes file if it doesn't exist
    if not exist routes\api.php (
        echo Creating routes/api.php file...
        echo ^<?php > routes\api.php
        echo. >> routes\api.php
        echo use Illuminate\Http\Request; >> routes\api.php
        echo use Illuminate\Support\Facades\Route; >> routes\api.php
        echo. >> routes\api.php
        echo /*^| >> routes\api.php
        echo ^|-------------------------------------------------------------------------->> routes\api.php
        echo ^| API Routes >> routes\api.php
        echo ^|-------------------------------------------------------------------------->> routes\api.php
        echo ^| >> routes\api.php
        echo ^| Here is where you can register API routes for your application. These >> routes\api.php
        echo ^| routes are loaded by the RouteServiceProvider and all of them will >> routes\api.php
        echo ^| be assigned to the "api" middleware group. Make something great! >> routes\api.php
        echo ^|>> routes\api.php
        echo */>> routes\api.php
        echo. >> routes\api.php
        echo Route::middleware('auth:api'^)->get('/user', function (Request $request^) {>> routes\api.php
        echo     return $request-^>user(^);>> routes\api.php
        echo }^);>> routes\api.php
    )
)

:: Display completion message
echo.
echo ===========================
echo Setup completed for project: %project_name%
if /i "%install_api%"=="y" echo - API features enabled
if /i "%install_jwt%"=="y" echo - JWT authentication installed
echo - npm install completed
echo - npm run build completed
echo.
echo Your Laravel project is ready!
echo.
echo If you want to start the development server, run:
echo cd %project_name% ^&^& npm run dev
echo ===========================

:: Keep the window open
pause
exit /b 0