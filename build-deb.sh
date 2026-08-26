#!/usr/bin/env bash
#
# Самодостаточная сборка .deb пакета meeting-informer.
# Не требует debhelper: собирает дерево пакета вручную и упаковывает
# через `dpkg-deb --build`. Используется в системе без debhelper.
#
# Результат: dist/meeting-informer_<version>_all.deb
set -euo pipefail
cd "$(dirname "$0")"

NAME="meeting-informer"
VERSION="$(python3 -c "import meeting_informer, sys; sys.stdout.write(meeting_informer.__version__)")"
DEB_VERSION="${VERSION}-1"
ARCH="all"
MAINTAINER="Alexey Bespalov <bespalov.alexey@uandex.ru>"

STAGE="debuild/${NAME}"
OUT="dist"
rm -rf "$STAGE" "$OUT"
mkdir -p "$STAGE" "$OUT"
trap 'rm -rf "$STAGE"' EXIT

echo "== сборочное дерево: $STAGE (version $DEB_VERSION) =="

# --- Python-пакет ---
install -d "$STAGE/usr/lib/${NAME}"
cp -a meeting_informer "$STAGE/usr/lib/${NAME}/meeting_informer"
find "$STAGE/usr/lib/${NAME}/meeting_informer" -name '__pycache__' -type d -prune -exec rm -rf {} +

# --- Лаунчер: информатор (подхват окружения графической сессии) ---
install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/meeting-informer" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
# systemd --user не всегда передаёт переменные графической сессии (Wayland,
# D-Bus). Подхватываем их из окружения живущего процесса GNOME.
SESSION_PID=""
for probe in gnome-shell gnome-session-binary; do
    pid="$(pgrep -u "$USER" -f "$probe" 2>/dev/null | head -n1 || true)"
    if [ -n "${pid}" ]; then SESSION_PID="${pid}"; break; fi
done
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ] && [ -n "${SESSION_PID}" ] \
   && [ -r "/proc/${SESSION_PID}/environ" ]; then
    while IFS= read -r -d '' entry; do
        case "${entry}" in
            WAYLAND_DISPLAY=*|DISPLAY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_RUNTIME_DIR=*|XAUTHORITY=*)
                export "${entry}" ;;
        esac
    done < "/proc/${SESSION_PID}/environ"
fi
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
    echo "meeting-informer: нет графической сессии (WAYLAND_DISPLAY/DISPLAY), выходим." >&2
    exit 0
fi
export PYTHONPATH="/usr/lib/__NAME__${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m meeting_informer "$@"
SH
sed -i "s|__NAME__|${NAME}|g" "$STAGE/usr/bin/meeting-informer"
chmod 0755 "$STAGE/usr/bin/meeting-informer"

# --- Лаунчер: CLI-валидатор ---
cat > "$STAGE/usr/bin/meeting-informer-update" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="/usr/lib/__NAME__${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m meeting_informer.updater "$@"
SH
sed -i "s|__NAME__|${NAME}|g" "$STAGE/usr/bin/meeting-informer-update"
chmod 0755 "$STAGE/usr/bin/meeting-informer-update"

# --- Пользовательская systemd-служба ---
install -d "$STAGE/usr/lib/systemd/user"
cat > "$STAGE/usr/lib/systemd/user/${NAME}.service" <<UNIT
[Unit]
Description=Информатор рабочих встреч
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/meeting-informer
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
UNIT

# --- Документация и скилл ---
install -d "$STAGE/usr/share/${NAME}/skills/meeting-informer"
install -m 0644 README.md "$STAGE/usr/share/${NAME}/README.md"
install -m 0644 skills/meeting-informer/SKILL.md "$STAGE/usr/share/${NAME}/skills/meeting-informer/SKILL.md"

install -d "$STAGE/usr/share/doc/${NAME}"
install -m 0644 debian/copyright "$STAGE/usr/share/doc/${NAME}/copyright"
gzip -c -9 -n debian/changelog > "$STAGE/usr/share/doc/${NAME}/changelog.Debian.gz"

# --- DEBIAN/control и поддерживающие скрипты ---
install -d "$STAGE/DEBIAN"
SIZE_KB="$(du -sk "$STAGE/usr" | awk '{print $1}')"
install -m 0644 debian/changelog "$STAGE/DEBIAN/changelog"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: ${NAME}
Version: ${DEB_VERSION}
Architecture: ${ARCH}
Maintainer: ${MAINTAINER}
Installed-Size: ${SIZE_KB}
Depends: python3, python3-gi, gir1.2-gtk-3.0, pulseaudio-utils, sound-theme-freedesktop
Section: utils
Priority: optional
Description: Local meeting reminder with mandatory GTK dialogs
 Локальный информатор рабочих встреч: обязательное окно поверх остальных
 окон и повторяемый системный звук за 15 минут, 5 минут и 1 минуту до
 встречи и в момент её начала. Читает расписание из локального текстового
 файла, работает только в локальной графической сессии (GNOME/Wayland),
 не зависит от браузера, календаря или интернета.
 .
 Запускается автоматически при входе пользователя; напоминания остаются на
 экране до подтверждения.
EOF

# postinst: шаблон расписания, скилл, включение пользовательской службы
cat > "$STAGE/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
# Пользователь, от имени которого установили пакет (важно при sudo dpkg -i).
TARGET_USER="${SUDO_USER:-$(id -un)}"
HOME_DIR="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[ -z "$HOME_DIR" ] && HOME_DIR="/home/$TARGET_USER"

# 1) Шаблон файла расписания
DATA="$HOME_DIR/.local/share/meeting-informer"
mkdir -p "$DATA"
if [ ! -f "$DATA/events.txt" ]; then
    cat > "$DATA/events.txt" <<'TMPL'
# Расписание встреч. Формат: YYYY-MM-DD HH:MM | Название
# Каждая встреча напомнит за 15 мин, 5 мин, 1 мин и в момент начала.

2026-08-26 09:00 | Пример встречи
TMPL
fi

# 2) Pi-скилл в домашний каталог пользователя
if [ -d "$HOME_DIR/.agents/skills" ]; then
    mkdir -p "$HOME_DIR/.agents/skills/meeting-informer"
    cp /usr/share/meeting-informer/skills/meeting-informer/SKILL.md \
       "$HOME_DIR/.agents/skills/meeting-informer/SKILL.md" 2>/dev/null || true
fi

# 3) Включить и запустить пользовательскую службу (мягко).
# Через runuser имитируем контекст пользователя для systemctl --user.
if command -v systemctl >/dev/null 2>&1; then
    RUNTIME="/run/user/$(id -u "$TARGET_USER")"
    if command -v runuser >/dev/null 2>&1 && [ "$(id -u)" = "0" ]; then
        if runuser -u "$TARGET_USER" -- env XDG_RUNTIME_DIR="$RUNTIME" \
            systemctl --user enable --now meeting-informer.service 2>/dev/null; then
            echo "Служба meeting-informer включена и запущена для $TARGET_USER."
        else
            echo "Включите службу вручную: systemctl --user enable --now meeting-informer.service"
        fi
    else
        if systemctl --user enable --now meeting-informer.service 2>/dev/null; then
            echo "Служба meeting-informer включена и запущена."
        else
            echo "Включите службу вручную: systemctl --user enable --now meeting-informer.service"
        fi
    fi
fi
exit 0
SH
chmod 0755 "$STAGE/DEBIAN/postinst"

# postrm: отключить пользовательскую службу при удалении
cat > "$STAGE/DEBIAN/postrm" <<'SH'
#!/bin/sh
set -e
TARGET_USER="${SUDO_USER:-$(id -un)}"
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    RUNTIME="/run/user/$(id -u "$TARGET_USER")"
    if command -v runuser >/dev/null 2>&1 && [ "$(id -u)" = "0" ]; then
        runuser -u "$TARGET_USER" -- env XDG_RUNTIME_DIR="$RUNTIME" \
            systemctl --user disable meeting-informer.service 2>/dev/null || true
    elif command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable meeting-informer.service 2>/dev/null || true
    fi
fi
exit 0
SH
chmod 0755 "$STAGE/DEBIAN/postrm"

# --- Сборка ---
echo "== сборка .deb =="
dpkg-deb --build --root-owner-group "$STAGE" "$OUT/${NAME}_${DEB_VERSION}_${ARCH}.deb"
echo "== готово: $OUT/${NAME}_${DEB_VERSION}_${ARCH}.deb =="
