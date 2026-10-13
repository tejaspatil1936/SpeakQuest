#!/usr/bin/env bash
# Run a command with AWS credentials from the environment or ./.env.
#
# The SDK credential chain is used as-is when AWS_ACCESS_KEY_ID or
# AWS_PROFILE is already set. Otherwise ./.env is read; besides the standard
# AWS_* names it accepts AWSKEY1 (access key id) / AWSKEY2 (secret), the names
# this project's .env happened to use. Values are exported to the child
# process only and never printed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "${AWS_ACCESS_KEY_ID:-}" && -z "${AWS_PROFILE:-}" && -f "$ROOT/.env" ]]; then
  while IFS='=' read -r key value || [[ -n "${key:-}" ]]; do
    [[ "$key" =~ ^[[:space:]]*# || -z "$key" ]] && continue
    value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
    case "$key" in
      AWS_ACCESS_KEY_ID|AWSKEY1) export AWS_ACCESS_KEY_ID="$value" ;;
      AWS_SECRET_ACCESS_KEY|AWSKEY2) export AWS_SECRET_ACCESS_KEY="$value" ;;
      AWS_SESSION_TOKEN) export AWS_SESSION_TOKEN="$value" ;;
      AWS_REGION|AWS_DEFAULT_REGION) export AWS_REGION="$value" ;;
    esac
  done < "$ROOT/.env"
fi
export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
export AWS_DEFAULT_REGION="$AWS_REGION"
exec "$@"
