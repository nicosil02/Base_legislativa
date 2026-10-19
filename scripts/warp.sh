#!/usr/bin/env bash
# Cloudflare WARP en modo proxy (SOCKS5 :40000) para yt-dlp: YouTube bloquea
# las IPs de datacenter de Actions ("not a bot").
#
# Sale con 1 si WARP no queda "Connected". Los workflows corren este paso con
# continue-on-error: lo que no depende de YouTube sigue, y el paso queda en
# rojo en la corrida, que es lo que mira el vigia (sistema/salud.py).
set -uo pipefail

curl -fsSL --retry 3 --retry-delay 2 --retry-all-errors https://pkg.cloudflareclient.com/pubkey.gpg \
  | sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/cloudflare-client.list
sudo apt-get update -qq
sudo apt-get install -y -qq cloudflare-warp || { echo "::warning::WARP no se pudo instalar"; exit 1; }
sudo systemctl enable --now warp-svc
sleep 3
for intento in 1 2 3; do
  warp-cli --accept-tos registration show > /dev/null 2>&1 || warp-cli --accept-tos registration new
  warp-cli --accept-tos mode proxy
  warp-cli --accept-tos proxy port 40000
  warp-cli --accept-tos connect
  for _ in $(seq 10); do
    if warp-cli --accept-tos status | grep -q Connected; then
      warp-cli --accept-tos status
      exit 0
    fi
    sleep 2
  done
  echo "[warp] intento $intento sin conectar, reintento..."
  warp-cli --accept-tos disconnect || true
done
warp-cli --accept-tos status || true
echo "::warning::WARP no conecto: lo de YouTube va a fallar en esta corrida"
exit 1
