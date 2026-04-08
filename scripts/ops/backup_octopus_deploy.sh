#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  backup_octopus_deploy.sh --source <octopus-repo-dir> --target <backup-dir>
  backup_octopus_deploy.sh [source-repo-dir] [backup-dir]

Copies <source>/.deploy into <target>/.deploy.

Defaults:
  source-repo-dir  current checkout

Notes:
  - backup-dir is required
  - provider-auth temporary scratch directories are excluded
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_REPO="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TARGET_DIR=""
POSITIONAL=()

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
    --source=*)
      SOURCE_REPO="${1#*=}"
      shift
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
    --target=*)
      TARGET_DIR="${1#*=}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [ "${#POSITIONAL[@]}" -gt 0 ]; then
  SOURCE_REPO="${POSITIONAL[0]}"
fi

if [ "${#POSITIONAL[@]}" -gt 1 ]; then
  TARGET_DIR="${POSITIONAL[1]}"
fi

if [ "${#POSITIONAL[@]}" -gt 2 ]; then
  echo "Too many arguments" >&2
  usage >&2
  exit 1
fi

if [ -z "${TARGET_DIR}" ]; then
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
