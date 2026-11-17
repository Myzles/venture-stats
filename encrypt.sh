#!/usr/bin/env bash
# Encrypts stats.json for the board (public key only; the private key lives in the board's scheduled task)
set -euo pipefail
openssl rand -hex 32 > k.tmp
openssl enc -aes-256-cbc -pbkdf2 -salt -in stats.json -out stats.enc -pass file:k.tmp
openssl pkeyutl -encrypt -pubin -inkey board_pub.pem -pkeyopt rsa_padding_mode:oaep -in k.tmp -out stats.key.enc
rm -f k.tmp stats.json
