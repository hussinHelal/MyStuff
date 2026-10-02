# createModels.ps1
# Usage (PowerShell or Cmder), run from the Laravel project root:
#   powershell -ExecutionPolicy Bypass -File .\createModels.ps1
#   powershell -ExecutionPolicy Bypass -File .\createModels.ps1 Products Cart
#
# For each model it makes:
#   app/Models/<Name>.php                           (+ migration)
#   app/Http/Controllers/<Name>/<Name>Controller.php (resource controller)
#   resources/views/<name>/{index,create,edit,show}.blade.php
# If a loose controller (app/Http/Controllers/<Name>Controller.php) already
# exists, it is moved into its own folder and its namespace is fixed.

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Models
)

$defaultModels = @("Products", "ContactUs", "Cart", "Wishlist", "Home", "Users", "Shop",
                   "Roles", "Staff", "Orders", "Notification", "AboutUs", "Gallery")

if (-not $Models -or $Models.Count -eq 0) { $Models = $defaultModels }

if (-not (Test-Path "artisan")) {
    Write-Host "artisan not found. Run this script from your Laravel project root." -ForegroundColor Red
    exit 1
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Utf8 {
    param([string]$Path, [string]$Content)
    $full = Join-Path (Get-Location).Path $Path
    [System.IO.File]::WriteAllText($full, $Content, $utf8NoBom)
}

function Read-Utf8 {
    param([string]$Path)
    $full = Join-Path (Get-Location).Path $Path
    return [System.IO.File]::ReadAllText($full)
}

Write-Host "Creating $($Models.Count) models, controllers and views..." -ForegroundColor Cyan

foreach ($model in $Models) {
    Write-Host "`n== $model ==" -ForegroundColor Yellow

    $controllerDir  = "app/Http/Controllers/$model"
    $controllerFile = "$controllerDir/${model}Controller.php"
    $looseController = "app/Http/Controllers/${model}Controller.php"
    $viewDir = "resources/views/" + $model.ToLower()

    # ---- Model + migration ----
    if ((Test-Path "app/Models/$model.php") -or (Test-Path "app/$model.php")) {
        Write-Host "Model already exists, skipping model/migration."
    } else {
        php artisan make:model $model -m
    }

    # ---- Controller folder ----
    New-Item -ItemType Directory -Force -Path $controllerDir | Out-Null

    if (Test-Path $looseController) {
        if (Test-Path $controllerFile) {
            Write-Host "Controller already in its folder; leaving loose one untouched." -ForegroundColor DarkYellow
        } else {
            Move-Item $looseController $controllerFile
            $code = Read-Utf8 $controllerFile
            $code = $code -replace 'namespace App\\Http\\Controllers;',
                "namespace App\Http\Controllers\$model;`r`n`r`nuse App\Http\Controllers\Controller;"
            Write-Utf8 $controllerFile $code
            Write-Host "Moved existing controller into $controllerDir"
        }
    } elseif (-not (Test-Path $controllerFile)) {
        php artisan make:controller "$model/${model}Controller" --resource --model=$model
    } else {
        Write-Host "Controller already exists, skipping."
    }

    # ---- Views folder ----
    New-Item -ItemType Directory -Force -Path $viewDir | Out-Null
    foreach ($view in @("index", "create", "edit", "show")) {
        $viewFile = "$viewDir/$view.blade.php"
        if (-not (Test-Path $viewFile)) {
            Write-Utf8 $viewFile "<div>`r`n    <!-- $model $view -->`r`n</div>`r`n"
        }
    }
    Write-Host "Views ready in $viewDir"
}

Write-Host "`nDone creating $($Models.Count) models, controllers and views." -ForegroundColor Green
