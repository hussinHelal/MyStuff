@echo off

call php artisan optimize:clear && php artisan cache:clear && php artisan route:clear  && php artisan view:clear && php artisan config:clear
