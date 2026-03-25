#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: backup_octopus_deploy.sh --source <octopus-repo-dir> --target <backup-dir>

Copies <source>/.deploy into <target>/.deploy.
Both --source and --target are required.
EOF
}

SOURCE_REPO=""
TARGET_DIR=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --source" >&2
        usage >&2
        exit 1
      fi
      SOURCE_REPO="$2"
      shift 2
      ;;
    --target)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --target" >&2
        usage >&2
        exit 1
      fi
      TARGET_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ -z "${SOURCE_REPO}" ] || [ -z "${TARGET_DIR}" ]; then
  usage >&2
  exit 1
fi

if [ ! -d "${SOURCE_REPO}" ]; then
  echo "Missing source repo: ${SOURCE_REPO}" >&2
  exit 1
fi

if [ ! -d "${SOURCE_REPO}/.deploy" ]; then
  echo "Missing source deploy dir: ${SOURCE_REPO}/.deploy" >&2
  exit 1
fi

mkdir -p "${TARGET_DIR}"

echo "Backing up ${SOURCE_REPO}/.deploy -> ${TARGET_DIR}/.deploy"
rsync -a --delete \
  --exclude 'provider-auth/*/tmp/' \
  --exclude 'provider-auth/*/.tmp/' \
  "${SOURCE_REPO}/.deploy/" \
  "${TARGET_DIR}/.deploy/"

echo "Backup complete: ${TARGET_DIR}/.deploy"
