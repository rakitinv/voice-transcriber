#!/usr/bin/env bash
# Общие функции для скриптов сборки и установки (Linux / Git Bash).

release_script_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

repo_root() {
  cd "$(release_script_dir)/../.." && pwd
}

import_release_env() {
  local env_file
  env_file="$(release_script_dir)/release.env"
  [[ -f "$env_file" ]] || return 0
  set -a
  # release.env часто копируют с Windows (CRLF) — bash иначе падает на $'\r'.
  # shellcheck source=/dev/null
  source <(sed 's/\r$//' "$env_file")
  set +a
}

release_tag() {
  if [[ -n "${VT_RELEASE_TAG:-}" ]]; then
    echo "${VT_RELEASE_TAG// /}"
    return
  fi
  local vf
  vf="$(repo_root)/VERSION"
  if [[ -f "$vf" ]]; then
    local v
    v="$(tr -d '[:space:]' < "$vf")"
    if [[ -n "$v" ]]; then
      echo "v${v}"
      return
    fi
  fi
  if command -v git >/dev/null 2>&1; then
    local t
    t="$(git -C "$(repo_root)" describe --tags --always 2>/dev/null || true)"
    if [[ -n "$t" ]]; then
      echo "$t"
      return
    fi
  fi
  date +%Y.%m.%d
}

release_output_dir() {
  local base tag root
  root="$(repo_root)"
  tag="$(release_tag)"
  base="${VT_RELEASE_DIR:-dist/release}"
  if [[ "$base" != /* ]]; then
    base="$root/$base"
  fi
  echo "${base%/}/voice-transcriber-${tag}"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Ошибка: команда '$1' не найдена в PATH. $2" >&2
    exit 1
  fi
}

release_step() {
  echo ""
  echo "==> $*"
}

# Публичные URL из release.env → файл в дистрибутиве (runtime на сервере, не только build-args).
write_public_urls_env() {
  local dest="$1"
  local server_env="${VT_SERVER_ENV_FILE:-/etc/voice-transcriber/voice-transcriber.env}"
  local -a lines=()
  [[ -n "${VT_PUBLIC_API_URL:-}" ]] && lines+=("VT_PUBLIC_API_URL=${VT_PUBLIC_API_URL}")
  [[ -n "${VT_WEBUI_ORIGIN:-}" ]] && lines+=("VT_WEBUI_ORIGIN=${VT_WEBUI_ORIGIN}")
  [[ -n "${VT_ADMIN_WEBUI_ORIGIN:-}" ]] && lines+=("VT_ADMIN_WEBUI_ORIGIN=${VT_ADMIN_WEBUI_ORIGIN}")
  [[ -n "${VT_ADMIN_WEBUI_ORIGINS:-}" ]] && lines+=("VT_ADMIN_WEBUI_ORIGINS=${VT_ADMIN_WEBUI_ORIGINS}")
  ((${#lines[@]})) || return 0
  {
    echo "# Сгенерировано при сборке дистрибутива (scripts/release/release.env)."
    echo "# Скопируйте в ${server_env} на сервере — сервис api читает их при compose up,"
    echo "# иначе OAuth админки вернёт: Admin OAuth requires VT_ADMIN_WEBUI_ORIGIN(S)..."
    echo ""
    printf '%s\n' "${lines[@]}"
  } >"$dest"
  echo "  public-urls.env -> $dest"
}

# Предупреждение, если на сервере нет allowlist для admin OAuth (частая ошибка после обновления).
warn_if_admin_oauth_env_missing() {
  local server_env="$1"
  local hints_file="$2"
  [[ -f "$hints_file" ]] || return 0
  local hint_origin
  hint_origin="$(grep -E '^VT_ADMIN_WEBUI_ORIGIN=' "$hints_file" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true)"
  [[ -n "$hint_origin" ]] || return 0
  if [[ -f "$server_env" ]] && grep -qE '^VT_ADMIN_WEBUI_ORIGIN=' "$server_env" 2>/dev/null; then
    return 0
  fi
  if [[ -f "$server_env" ]] && grep -qE '^VT_ADMIN_WEBUI_ORIGINS=' "$server_env" 2>/dev/null; then
    return 0
  fi
  echo "" >&2
  echo "=== ВНИМАНИЕ: OAuth админки не заработает без runtime-переменной на сервисе api ===" >&2
  if [[ -f "$server_env" ]]; then
    echo "В ${server_env} нет VT_ADMIN_WEBUI_ORIGIN / VT_ADMIN_WEBUI_ORIGINS." >&2
  else
    echo "Файл ${server_env} не найден." >&2
  fi
  echo "Образ admin-webui собран с landing URL: ${hint_origin}" >&2
  echo "Добавьте в ${server_env} (см. также deploy/docker/public-urls.env в дистрибутиве):" >&2
  echo "  VT_ADMIN_WEBUI_ORIGIN=${hint_origin}" >&2
  echo "Затем пересоздайте api: docker compose --env-file ${server_env} up -d --force-recreate api" >&2
  echo "  (docker compose restart api НЕ подхватывает новые переменные)" >&2
  echo "================================================================" >&2
  echo "" >&2
}

# Compose env_file читает deploy/docker/.env (копия /etc/…); symlink на путь вне каталога compose иногда ломает старт api.
sync_compose_dotenv_from_server() {
  local compose_dir="$1"
  local server_env="$2"
  local dotenv="$compose_dir/.env"
  [[ -f "$server_env" ]] || return 0
  if cp -f "$server_env" "$dotenv" 2>/dev/null; then
    echo "  скопировано: $server_env -> $dotenv"
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo cp -f "$server_env" "$dotenv"; then
    echo "  скопировано (sudo): $server_env -> $dotenv"
    if command -v sudo >/dev/null 2>&1; then
      sudo chmod 0640 "$dotenv" 2>/dev/null || true
    fi
    return 0
  fi
  echo "Не удалось скопировать $server_env в $dotenv" >&2
  return 1
}

verify_api_admin_oauth_env_in_container() {
  local compose_dir="$1"
  shift
  local -a compose_cmd=("$@")
  local server_env="${ENV_FILE:-/etc/voice-transcriber/voice-transcriber.env}"
  local expected actual
  [[ -f "$server_env" ]] || return 0
  expected="$(grep -E '^VT_ADMIN_WEBUI_ORIGIN=' "$server_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true)"
  [[ -n "$expected" ]] || return 0
  actual="$(cd "$compose_dir" && "${compose_cmd[@]}" exec -T api printenv VT_ADMIN_WEBUI_ORIGIN 2>/dev/null | tr -d '\r' || true)"
  if [[ -z "$actual" ]]; then
    echo "" >&2
    echo "ОШИБКА: контейнер api не видит VT_ADMIN_WEBUI_ORIGIN (в $server_env задано: $expected)." >&2
    echo "  cd $compose_dir && ${compose_cmd[*]} --env-file $server_env up -d --force-recreate api" >&2
    echo "" >&2
    return 1
  fi
  if [[ "$actual" != "$expected" ]]; then
    echo "Предупреждение: в api VT_ADMIN_WEBUI_ORIGIN=$actual (в $server_env: $expected)." >&2
  fi
  return 0
}

# Объединить VT_COMPOSE_PROFILES из release.env и серверного env-файла.
merge_compose_profiles() {
  local server_env="$1"
  local from_server="" merged=""
  [[ -f "$server_env" ]] && from_server="$(grep -E '^VT_COMPOSE_PROFILES=' "$server_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true)"
  merged="${VT_COMPOSE_PROFILES:-}"
  if [[ -n "$from_server" ]]; then
    if [[ -n "$merged" ]]; then
      merged="${merged},${from_server}"
    else
      merged="$from_server"
    fi
  fi
  VT_COMPOSE_PROFILES="$merged"
}

compose_profiles_include() {
  local needle="$1"
  local csv="${VT_COMPOSE_PROFILES:-}"
  [[ -n "$csv" ]] || return 1
  local p
  IFS=',' read -ra PROFS <<< "$csv"
  for p in "${PROFS[@]}"; do
    p="${p// /}"
    [[ "$p" == "$needle" ]] && return 0
  done
  return 1
}

# При profile gpu: CPU-воркеры не должны конкурировать с GPU за asr_final / diarization / asr_fast.
apply_gpu_worker_exclusivity() {
  local compose_dir="$1"
  shift
  local -a compose_cmd=("$@")
  local server_env="${ENV_FILE:-/etc/voice-transcriber/voice-transcriber.env}"
  compose_profiles_include gpu || return 0

  release_step "GPU profile: останавливаем CPU-конкурентов (worker-final, diarization-worker)"
  (cd "$compose_dir" && "${compose_cmd[@]}" stop worker-final 2>/dev/null || true)
  (cd "$compose_dir" && "${compose_cmd[@]}" stop diarization-worker 2>/dev/null || true)

  if [[ -f "$server_env" ]]; then
    local q
    q="$(grep -E '^VT_MAIN_WORKER_QUEUES=' "$server_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true)"
    if [[ -z "$q" ]] || [[ "$q" == *asr_fast* ]]; then
      echo "" >&2
      echo "=== ВНИМАНИЕ: GPU final ASR — уберите asr_fast из основного worker ===" >&2
      echo "Иначе transcribe_slice (параллельная нарезка §17) может уйти на CPU worker." >&2
      echo "В ${server_env} задайте, например:" >&2
      echo "  VT_MAIN_WORKER_QUEUES=asr,cleanup          # если поднят worker-llm (profile scale_llm)" >&2
      echo "  VT_MAIN_WORKER_QUEUES=asr,llm,cleanup       # если worker-llm не используется" >&2
      echo "Слайсы asr_fast обрабатывает worker-final-gpu (очереди asr_fast,asr_final)." >&2
      echo "================================================================" >&2
      echo "" >&2
    fi
  fi
}

# Базовый стек без profile-only сервисов (Compose v5 иначе собирает и diarization-worker).
compose_default_build_services() {
  echo "migrate api admin-api worker worker-final webui admin-webui"
}

# Сервисы, которые нужно собрать для optional compose profile (не весь стек).
compose_profile_build_services() {
  case "${1// /}" in
    gpu) echo "worker-final-gpu diarization-worker-gpu" ;;
    diarization) echo "diarization-worker" ;;
    scale_llm) echo "worker-llm" ;;
    test) echo "tests" ;;
    *) echo "" ;;
  esac
}

# Профили, обязательные для docker compose build <service>.
compose_service_required_profiles() {
  case "${1// /}" in
    worker-final-gpu|diarization-worker-gpu) echo "gpu" ;;
    diarization-worker) echo "diarization" ;;
    worker-llm) echo "scale_llm" ;;
    tests) echo "test" ;;
    *) echo "" ;;
  esac
}

compose_build_kit_env() {
  export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-1}"
  export COMPOSE_DOCKER_CLI_BUILD="${COMPOSE_DOCKER_CLI_BUILD:-1}"
  export BUILDX_NO_DEFAULT_ATTESTATIONS="${BUILDX_NO_DEFAULT_ATTESTATIONS:-1}"
  export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"
}

# Собрать только перечисленные сервисы; для profile-only — по одному с --profile.
compose_build_services() {
  local -a names=() s profs profile_args=()
  local -A seen=()
  for s in "$@"; do
    [[ -z "$s" ]] && continue
    [[ -n "${seen[$s]+x}" ]] && continue
    seen["$s"]=1
    names+=("$s")
  done
  ((${#names[@]})) || return 0

  local -a default_batch=() profiled=()
  for s in "${names[@]}"; do
    profs=()
    read -ra profs <<< "$(compose_service_required_profiles "$s")"
    if ((${#profs[@]})); then
      profiled+=("$s")
    else
      default_batch+=("$s")
    fi
  done

  if ((${#default_batch[@]})); then
    release_step "Build services: ${default_batch[*]}"
    docker compose build "${default_batch[@]}"
  fi
  for s in "${profiled[@]}"; do
    profile_args=()
    read -ra profs <<< "$(compose_service_required_profiles "$s")"
    for p in "${profs[@]}"; do
      [[ -n "$p" ]] && profile_args+=(--profile "$p")
    done
    release_step "Build service: $s (profile: ${profs[*]})"
    # --no-deps: не пересобирать migrate/api (depends_on; базовый build уже прошёл).
    docker compose "${profile_args[@]}" build "$s"
  done
}

# Объединить VT_DOCKER_EXTRA_SERVICES и сервисы из VT_DOCKER_COMPOSE_PROFILES (без дубликатов).
compose_optional_build_services() {
  local extra="${VT_DOCKER_EXTRA_SERVICES:-}"
  local profiles="${VT_DOCKER_COMPOSE_PROFILES:-}"
  local -a out=() part prof svcs
  local -A seen=()
  if [[ -n "$extra" ]]; then
    read -ra part <<< "$extra"
    for s in "${part[@]}"; do
      [[ -z "$s" ]] && continue
      [[ -n "${seen[$s]+x}" ]] && continue
      seen["$s"]=1
      out+=("$s")
    done
  fi
  if [[ -n "$profiles" ]]; then
    IFS=',' read -ra prof <<< "$profiles"
    for p in "${prof[@]}"; do
      p="${p// /}"
      [[ -z "$p" ]] && continue
      svcs="$(compose_profile_build_services "$p")"
      if [[ -z "$svcs" ]]; then
        echo "Предупреждение: неизвестный compose profile '$p' (VT_DOCKER_COMPOSE_PROFILES)" >&2
        continue
      fi
      read -ra part <<< "$svcs"
      for s in "${part[@]}"; do
        [[ -n "${seen[$s]+x}" ]] && continue
        seen["$s"]=1
        out+=("$s")
      done
    done
  fi
  printf '%s\n' "${out[@]}"
}

# Имена образов для docker save: базовый compose + сервисы из профилей
# (VT_DOCKER_COMPOSE_PROFILES / VT_COMPOSE_PROFILES). Без профилей worker-llm и *-gpu не попадают в tar.
compose_collect_export_images() {
  local docker_dir="$1"
  local -A seen=()
  local img prof_csv profile_args=() p
  cd "$docker_dir" || return 1

  _compose_export_add_images() {
    local line
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      [[ -n "${seen[$line]+x}" ]] && continue
      seen["$line"]=1
      printf '%s\n' "$line"
    done
  }

  docker compose config --images 2>/dev/null | sort -u | _compose_export_add_images

  prof_csv="${VT_DOCKER_COMPOSE_PROFILES:-}"
  if [[ -n "${VT_COMPOSE_PROFILES:-}" ]]; then
    if [[ -n "$prof_csv" ]]; then
      prof_csv="${prof_csv},${VT_COMPOSE_PROFILES}"
    else
      prof_csv="${VT_COMPOSE_PROFILES}"
    fi
  fi
  if [[ -n "$prof_csv" ]]; then
    IFS=',' read -ra PROFS <<< "$prof_csv"
    for p in "${PROFS[@]}"; do
      p="${p// /}"
      [[ -z "$p" ]] && continue
      svcs="$(compose_profile_build_services "$p")"
      if [[ -z "$svcs" ]]; then
        docker compose --profile "$p" config --images 2>/dev/null | sort -u | _compose_export_add_images
        continue
      fi
      read -ra svc_arr <<< "$svcs"
      for s in "${svc_arr[@]}"; do
        docker compose --profile "$p" config --images "$s" 2>/dev/null | sort -u | _compose_export_add_images
      done
    done
  fi
}
