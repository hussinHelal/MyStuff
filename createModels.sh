#!/bin/bash

default_models=("Products" "ContactUs" "Cart" "Wishlist" "Home" "Users" "Shop" "Roles" "Staff" "Orders" "Notification" "AboutUs" "Gallery")

if [ "$#" -gt 0 ]; then
 models=("$@")
else 
 models=("${default_models[@]}")
fi 

echo "Creating $[#models[@]} model and controller"
for model in "${models[@]}"; do
 php artisan make:model "$model" -mcr
done

echo "Done Creating ${#models[@]} model and controller. "
