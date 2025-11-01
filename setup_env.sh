#!/usr/bin/env bash
set -e

# ──────────────────────────────────────────────────────────────
# Colours & helpers
# ──────────────────────────────────────────────────────────────
RED='\033[0;31m'   GREEN='\033[0;32m'   YELLOW='\033[1;33m'   BLUE='\033[0;34m'   NC='\033[0m'
log()   { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
prompt(){ echo -e "${BLUE}[?]${NC} $*"; }

# ──────────────────────────────────────────────────────────────
# 1. Detect distribution
# ──────────────────────────────────────────────────────────────
detect_distro() {
    if [[ -f /etc/os-release ]]; then . /etc/os-release; DISTRO=$ID; else error "Cannot detect distro"; fi
    case $DISTRO in
        arch|archarm|manjaro*) DISTRO="arch" ;;
        fedora|centos|rhel)    DISTRO="fedora" ;;
        ubuntu|debian|pop|linuxmint) DISTRO="debian" ;;
        *) error "Unsupported distro: $DISTRO";;
    esac
    log "Detected distribution: $DISTRO"
}

# ──────────────────────────────────────────────────────────────
# 2. Choose web server
# ──────────────────────────────────────────────────────────────
choose_webserver() {
    echo
    prompt "Select web server for native PHP (Docker+Sail always available):"
    echo "   1) Apache"
    echo "   2) Nginx"
    read -rp "Enter choice [1-2]: " ws
    case $ws in 1) WEBSERVER="apache" ;; 2) WEBSERVER="nginx" ;; *) WEBSERVER="apache" ;; esac
    log "Web server chosen: $WEBSERVER"
}

# ──────────────────────────────────────────────────────────────
# 3. Install system packages (including Caja, Thunar, GVFS, VLC, etc.)
# ──────────────────────────────────────────────────────────────
install_packages() {
    log "Updating system and installing packages..."

    # Common packages
    COMMON_PKGS=(
        docker docker-compose php php-apache mariadb
        neovim nodejs npm fish
        ttf-firacode-nerd aircrack-ng clang llvm lld openssl elfutils
        linux-headers base-devel git curl wget snapd flatpak
    )

    # GUI / File manager extras
    case $DISTRO in
        arch)
            sudo pacman -Syu --noconfirm
            sudo pacman -S --noconfirm "${COMMON_PKGS[@]}" \
                caja thunar thunar-volman thunar-archive-plugin thunar-media-tags-plugin \
                tumbler catfish gvfs vlc

            if [[ $WEBSERVER == "nginx" ]]; then
                sudo pacman -S --noconfirm nginx-mainline php-fpm
            else
                sudo pacman -S --noconfirm apache
            fi
            sudo systemctl enable --now docker snapd
            sudo ln -sf /var/lib/snapd/snap /snap || true
            ;;

        fedora)
            sudo dnf update -y
            sudo dnf install -y "${COMMON_PKGS[@]}" \
                caja thunar thunar-volman thunar-archive-plugin thunar-media-tags-plugin \
                tumbler catfish gvfs vlc \
                php-json php-mbstring php-xml php-pdo php-mysqlnd \
                kernel-headers kernel-devel make gcc

            if [[ $WEBSERVER == "nginx" ]]; then
                sudo dnf install -y nginx php-fpm
            else
                sudo dnf install -y httpd
            fi
            sudo systemctl enable --now docker mariadb ${WEBSERVER}
            [[ $WEBSERVER == "nginx" ]] && sudo systemctl enable --now php-fpm
            ;;

        debian)
            sudo apt update && sudo apt upgrade -y
            sudo apt install -y "${COMMON_PKGS[@]}" \
                caja thunar thunar-volman thunar-archive-plugin thunar-media-tags-plugin \
                tumbler catfish gvfs vlc \
                php-cli php-mbstring php-xml php-bcmath php-zip php-mysql \
                build-essential ca-certificates gnupg

            if [[ $WEBSERVER == "nginx" ]]; then
                sudo apt install -y nginx php-fpm
            else
                sudo apt install -y apache2
            fi
            sudo systemctl enable --now docker mariadb ${WEBSERVER}
            [[ $WEBSERVER == "nginx" ]] && sudo systemctl enable --now php*-fpm
            ;;
    esac
}

# ──────────────────────────────────────────────────────────────
# 4. Install Composer (verified)
# ──────────────────────────────────────────────────────────────
install_composer() {
    log "Installing Composer..."
    EXPECTED="$(curl -s https://composer.github.io/installer.sig)"
    php -r "copy('https://getcomposer.org/installer','composer-setup.php');"
    ACTUAL="$(php -r "echo hash_file('sha384','composer-setup.php');")"
    [[ "$EXPECTED" != "$ACTUAL" ]] && error "Composer checksum mismatch!" && rm composer-setup.php && exit 1
    sudo php composer-setup.php --install-dir=/usr/local/bin --filename=composer
    rm composer-setup.php
    log "Composer $(composer --version)"
}

# ──────────────────────────────────────────────────────────────
# 5. GUI tools (VS Code, Sublime Text 4, Postman)
# ──────────────────────────────────────────────────────────────
install_gui_tools() {
    log "Installing VS Code, Sublime Text 4, Postman..."

    case $DISTRO in
        arch)
            sudo pacman -S --noconfirm code || true
            curl -fsSL https://download.sublimetext.com/sublimehq-pub.gpg | sudo pacman-key --add -
            sudo pacman-key --lsign-key 8A8F901A
            echo -e "\n[sublime-text]\nServer = https://download.sublimetext.com/arch/stable/x86_64" | sudo tee -a /etc/pacman.conf
            sudo pacman -Syu --noconfirm sublime-text
            sudo snap install postman
            ;;
        fedora)
            sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
            sudo sh -c 'cat > /etc/yum.repos.d/vscode.repo <<EOF
[code]
name=Visual Studio Code
baseurl=https://packages.microsoft.com/yumrepos/vscode
enabled=1
gpgcheck=1
gpgkey=https://packages.microsoft.com/keys/microsoft.asc
EOF'
            sudo dnf install -y code
            sudo rpm -v --import https://download.sublimetext.com/sublimehq-rpm-pub.gpg
            sudo dnf config-manager --add-repo https://download.sublimetext.com/rpm/stable/x86_64/sublime-text.repo
            sudo dnf install -y sublime-text
            sudo snap install postman
            ;;
        debian)
            wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > ms.gpg
            sudo install -o root -g root -m 644 ms.gpg /etc/apt/trusted.gpg.d/
            sudo sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list'
            sudo apt update && sudo apt install -y code
            wget -qO - https://download.sublimetext.com/sublimehq-pub.gpg | sudo apt-key add -
            echo "deb https://download.sublimetext.com/ apt/stable/" | sudo tee /etc/apt/sources.list.d/sublime-text.list
            sudo apt update && sudo apt install -y sublime-text
            sudo snap install postman
            ;;
    esac
}

# ──────────────────────────────────────────────────────────────
# 6. Docker non‑root access
# ──────────────────────────────────────────────────────────────
setup_docker() {
    log "Adding $USER to docker group..."
    sudo usermod -aG docker "$USER"
    warn "Log out / log back in for docker group to take effect."
}

# ──────────────────────────────────────────────────────────────
# 7. Auto‑generate web‑server config
# ──────────────────────────────────────────────────────────────
generate_web_config() {
    local proj_dir="$1"
    local docroot="$proj_dir/public"

    if [[ $WEBSERVER == "apache" ]]; then
        local conf="/etc/httpd/conf.d/000-laravel.conf"
        [[ $DISTRO == "debian" ]] && conf="/etc/apache2/sites-available/laravel.conf"

        log "Generating Apache vhost → $conf"
        sudo tee "$conf" > /dev/null <<EOF
<VirtualHost *:80>
    ServerName localhost
    DocumentRoot $docroot

    <Directory $docroot>
        AllowOverride All
        Require all granted
    </Directory>

    ErrorLog /var/log/${WEBSERVER}/laravel-error.log
    CustomLog /var/log/${WEBSERVER}/laravel-access.log combined
</VirtualHost>
EOF
        [[ $DISTRO == "debian" ]] && sudo a2ensite laravel.conf && sudo a2enmod rewrite
        sudo systemctl restart apache2 2>/dev/null || sudo systemctl restart httpd

    else # nginx
        local conf="/etc/nginx/conf.d/laravel.conf"
        log "Generating Nginx config → $conf"
        sudo tee "$conf" > /dev/null <<EOF
server {
    listen 80;
    server_name localhost;
    root $docroot;
    index index.php index.html;

    location / {
        try_files \$uri \$uri/ /index.php?\$query_string;
    }

    location ~ \.php$ {
        fastcgi_pass unix:/run/php/php-fpm.sock;
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME \$document_root\$fastcgi_script_name;
        include fastcgi_params;
    }
}
EOF
        sudo systemctl restart nginx
    fi

    log "Web‑server config generated and restarted."
}

# ──────────────────────────────────────────────────────────────
# 8. Create Laravel project with Sail + Vite
# ──────────────────────────────────────────────────────────────
create_laravel_project() {
    echo
    read -rp "Create a new Laravel project with Docker+Sail+Vite? (y/N): " ans
    [[ ! $ans =~ ^[Yy]$ ]] && { log "Skipping project creation."; return; }

    read -rp "Project name [laravel-app]: " proj
    proj=${proj:-laravel-app}
    log "Creating Laravel project → $proj"

    curl -s "https://laravel.build/$proj?with=mariadb,redis,mailpit" | bash
    cd "$proj"

    log "Installing NPM deps + building assets..."
    ./vendor/bin/sail npm install
    ./vendor/bin/sail npm run build

    # Auto‑generate web config for this project
    generate_web_config "$(pwd)"

    echo
    log "Laravel project ready!"
    echo "   cd $proj"
    echo "   ./vendor/bin/sail up -d          # start containers"
    echo "   ./vendor/bin/sail npm run dev   # Vite dev server"
    echo "   http://localhost                 # in browser"
    echo
}

# ──────────────────────────────────────────────────────────────
# 9. Final instructions
# ──────────────────────────────────────────────────────────────
final_instructions() {
    echo
    log "=== SETUP COMPLETE ==="
    echo
    echo "Web server: $WEBSERVER (auto‑configured)"
    echo "Docker + Laravel Sail + Vite: ready"
    echo "Fish shell: run 'fish' to try"
    echo
    echo "Next steps:"
    echo "   1. Log out / log back in (docker group)"
    echo "   2. cd laravel-app && ./vendor/bin/sail up -d"
    echo "   3. Vite dev: ./vendor/bin/sail npm run dev"
    echo "   4. Native server: sudo systemctl start mariadb $WEBSERVER"
    echo
    echo "Extra tools installed:"
    echo "   • Caja, Thunar + plugins (volman, archive, media-tags)"
    echo "   • Tumbler, Catfish, GVFS, VLC"
    echo "   • VS Code, Sublime Text 4, Postman"
    echo "   • Neovim, Node.js, Fish, Nerd Font, aircrack-ng, clang, llvm"
    echo
    warn "Your full Laravel + File Manager + Media stack is ready!"
}

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
main() {
    detect_distro
    choose_webserver
    install_packages
    install_composer
    install_gui_tools
    setup_docker
    create_laravel_project
    final_instructions
}
main
