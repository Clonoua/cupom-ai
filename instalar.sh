#!/bin/bash

# Instalador completo Cupom-IA

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Use: sudo ./install.sh"
  exit 1
fi

USER_HOME=$(eval echo "~$SUDO_USER")
INSTALL_DIR="/opt/cupom-ia"

echo "== Instalando dependências do sistema =="
apt update
apt install -y python3 python3-venv python3-pip curl

echo "== Parando serviço anterior se existir =="
systemctl stop cupom-ai.service 2>/dev/null || true

echo "== Criando diretório =="
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
chown -R $SUDO_USER:$SUDO_USER "$INSTALL_DIR"

echo "== Copiando arquivos =="
cp -rT . "$INSTALL_DIR"

cd "$INSTALL_DIR"

echo "== Criando ambiente virtual =="
sudo -u $SUDO_USER python3 -m venv venv
sudo -u $SUDO_USER bash -c "source venv/bin/activate && pip install --upgrade pip"
sudo -u $SUDO_USER bash -c "source venv/bin/activate && pip install -r requirements.txt"

echo "== Instalando Ollama se necessário =="
if ! command -v ollama &> /dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

echo "== Garantindo que Ollama esteja ativo =="
systemctl enable ollama || true
systemctl start ollama || true

echo "== Baixando modelo Qwen =="
ollama pull qwen2.5vl:7b || true

echo "== Criando serviço systemd =="
cat > /etc/systemd/system/cupom-ai.service <<EOF
[Unit]
Description=Cupom-IA FastAPI com Ollama Vision
After=network.target ollama.service

[Service]
User=$SUDO_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cupom-ai.service
systemctl restart cupom-ai.service

IP=$(hostname -I | awk '{print $1}')

echo ""
echo "====================================="
echo "Instalação concluída com sucesso 🚀"
echo "Acesse: http://$IP:8000/docs"
echo "Status: sudo systemctl status cupom-ai"
echo "Logs:   journalctl -u cupom-ai -f"
echo "====================================="