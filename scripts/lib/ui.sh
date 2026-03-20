#!/usr/bin/env bash
# Doctor output and display helpers.

doctor_output_has_token_rejection() {
  printf '%s\n' "${1:-}" | grep -q "Telegram rejected TELEGRAM_BOT_TOKEN"
}

format_doctor_output_for_operator() {
  printf '%s\n' "${1:-}" | while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "" )
        ;;
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*)
        ;;
      *"HTTP Request:"*)
        ;;
      *)
        printf '%s\n' "$line"
        ;;
    esac
  done
}

print_doctor_output_for_operator() {
  local output="${1:-}" line=""
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "$line" >&2
  done < <(format_doctor_output_for_operator "$output")
}
