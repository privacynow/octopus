#!/bin/sh
# Ensure bot-home volume is writable by bot user (uid 1000); then run as bot.
set -e
chown -R 1000:1000 /home/bot 2>/dev/null || true
exec gosu bot "$@"
