#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-codex-chat}"
APP_GROUP="${APP_GROUP:-codex-chat}"
POOL_GROUP="${POOL_GROUP:-codexchat}"
POOL_PREFIX="${LINUX_USER_POOL_PREFIX:-codexweb}"
POOL_START="${LINUX_USER_POOL_START:-1}"
POOL_SIZE="${LINUX_USER_POOL_SIZE:-100}"
SANDBOX_ROOT="${LINUX_SANDBOX_ROOT:-/var/lib/codex-chat/sandboxes}"
PROJECT_ROOT="${PROJECT_ROOT:-/opt/codex-chat}"
PROOT_BIN="${PROOT_BIN:-${PROJECT_ROOT}/tools/proot/usr/bin/proot}"
CODEX_EXEC_BIN="${CODEX_EXEC_BIN:-${PROJECT_ROOT}/tools/codex/bin/codex}"
SUDOERS_FILE="/etc/sudoers.d/codex-chat-runner"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if ! command -v setfacl >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y acl
fi

groupadd -f "${POOL_GROUP}"
mkdir -p "${SANDBOX_ROOT}"
chmod 711 /var/lib/codex-chat
chmod 711 "${SANDBOX_ROOT}"
setfacl -m "g:${POOL_GROUP}:x" "/home/${APP_USER}" "${PROJECT_ROOT}"
setfacl -R -m "g:${POOL_GROUP}:rx" "${PROJECT_ROOT}/tools"
setfacl -R -d -m "g:${POOL_GROUP}:rx" "${PROJECT_ROOT}/tools"

stop=$((POOL_START + POOL_SIZE - 1))
for index in $(seq "${POOL_START}" "${stop}"); do
  username="$(printf '%s%03d' "${POOL_PREFIX}" "${index}")"
  home_dir="/home/${username}"
  if ! id "${username}" >/dev/null 2>&1; then
    useradd \
      --create-home \
      --home-dir "${home_dir}" \
      --shell /usr/sbin/nologin \
      --gid "${POOL_GROUP}" \
      "${username}"
  fi

  passwd -l "${username}" >/dev/null 2>&1 || true
  usermod --shell /usr/sbin/nologin "${username}"

  sandbox="${SANDBOX_ROOT}/${username}"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/workspace"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/home"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/home/.codex"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/.guest-root"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/.guest-root/home/codex"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/.guest-root/opt/codex"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/.guest-root/workspace"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/.guest-root/tmp"
  install -d -o "${username}" -g "${POOL_GROUP}" -m 700 "${sandbox}/tmp"
  setfacl -m "m:rwx,u:${APP_USER}:rwx" "${sandbox}" "${sandbox}/workspace" "${sandbox}/home" "${sandbox}/home/.codex" "${sandbox}/.guest-root" "${sandbox}/tmp"
  setfacl -R -m "m:rwx,u:${APP_USER}:rwx,u:${username}:rwx" "${sandbox}"
  setfacl -d -m "u:${APP_USER}:rwx" "${sandbox}" "${sandbox}/workspace" "${sandbox}/home" "${sandbox}/home/.codex" "${sandbox}/.guest-root" "${sandbox}/tmp"
  setfacl -R -d -m "u:${username}:rwx" "${sandbox}" "${sandbox}/workspace" "${sandbox}/home" "${sandbox}/home/.codex" "${sandbox}/.guest-root" "${sandbox}/tmp"
done

cat >"${SUDOERS_FILE}" <<EOF
Defaults:${APP_USER} env_keep += "HOME PATH TMPDIR LD_LIBRARY_PATH"
${APP_USER} ALL=(%${POOL_GROUP}) NOPASSWD:SETENV: ${PROOT_BIN}
${APP_USER} ALL=(%${POOL_GROUP}) NOPASSWD:SETENV: ${CODEX_EXEC_BIN}
EOF
chmod 0440 "${SUDOERS_FILE}"
visudo -cf "${SUDOERS_FILE}" >/dev/null

echo "Provisioned ${POOL_SIZE} Linux users (${POOL_PREFIX}$(printf '%03d' "${POOL_START}")-${POOL_PREFIX}$(printf '%03d' "${stop}"))"
