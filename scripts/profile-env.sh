# shellcheck shell=bash
# Sourced, not run, by scripts/run.sh, scripts/docker-entrypoint.sh and
# scripts/runpod/runpod-start.sh, first thing: with STACK_PROFILE set, export
# the profile's [env] values (profiles/<name>.toml) for every variable the
# environment leaves unset. A bad profile name stops the start here, loudly.
if [ -n "${STACK_PROFILE:-}" ]; then
  _profile_env="$(python3 "$(dirname "${BASH_SOURCE[0]}")/../server/stack_config.py" profile-env)" || exit 1
  eval "$_profile_env"
  unset _profile_env
  echo "profile: $STACK_PROFILE"
fi
