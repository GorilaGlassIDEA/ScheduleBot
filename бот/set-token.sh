#!/usr/bin/env bash
# Сохраняет токен бота в secrets/bot_token со скрытым вводом:
# токен не светится ни на экране, ни в истории шелла, ни в git.
set -euo pipefail
cd "$(dirname "$0")"

read -rsp "Вставь токен от @BotFather (ввод скрыт): " token
echo

if [[ -z "$token" ]]; then
    echo "Пустой токен, ничего не сохранено." >&2
    exit 1
fi

# доступ ограничивает папка (700); сам файл 644, чтобы его мог
# прочитать непривилегированный пользователь внутри контейнера
mkdir -p secrets
chmod 700 secrets
printf '%s' "$token" > secrets/bot_token
chmod 644 secrets/bot_token
echo "Токен сохранён в secrets/bot_token."
echo "Теперь запускай: docker compose up -d --build"
