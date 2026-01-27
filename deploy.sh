#!/bin/bash

# Konfiguracja
SERVER="user@79-76-127-159.nip.io"
REMOTE_DIR="/var/www/netrc"

echo "Deploying to $SERVER..."

# Kopiuj index.html
echo "Copying index.html..."
scp public/index.html $SERVER:/tmp/

# Wykonaj na serwerze
ssh $SERVER << 'EOF'
    sudo mv /tmp/index.html /var/www/netrc/
    sudo chown www-data:www-data /var/www/netrc/index.html
    sudo chmod 644 /var/www/netrc/index.html
    echo "Deployment complete!"
EOF

echo "Done! Visit https://79-76-127-159.nip.io"
