#!/usr/bin/env bash
# One-time creation of a new hosted 1102tools MCP service on Cloudflare.
#
#   scripts/first_deploy_hosted.sh <slug>      e.g. scripts/first_deploy_hosted.sh bls-oews
#
# CI (publish-pypi.yml) only redeploys services that already exist and are
# listed in deploy/services.json with their Container application ID. This
# script does the first deploy by hand: it builds the image from
# deploy/<slug>/Dockerfile, creates the Worker, Container application,
# Durable Object, and custom domain, then prints the application ID to add
# to deploy/services.json. Run it from a clean checkout at origin/main.
#
# The only credential is your Cloudflare login (wrangler OAuth in the
# browser). No API key is typed or stored by this script.
set -euo pipefail

ACCOUNT_ID=846d3e41e48446abcd3570c0959f9fb5

die() { printf '\n\033[31mStopped:\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

slug=${1:-}
[ -n "$slug" ] || die "usage: scripts/first_deploy_hosted.sh <slug>   (for example: bls-oews)"
root=$(git rev-parse --show-toplevel 2>/dev/null) || die "run this inside the federal-contracting-mcps checkout"
cd "$root"
dir="deploy/$slug"
[ -f "$dir/wrangler.jsonc" ] || die "$dir/wrangler.jsonc not found"
worker=$(python3 -c "import json,re,sys; print(json.loads(re.sub(r'^\s*//.*$','',open(sys.argv[1]).read(),flags=re.M))['env']['production']['name'])" "$dir/wrangler.jsonc")
app="$worker-public"
domain=$(python3 -c "import json,re,sys; print(json.loads(re.sub(r'^\s*//.*$','',open(sys.argv[1]).read(),flags=re.M))['env']['production']['routes'][0]['pattern'])" "$dir/wrangler.jsonc")

step "1/5  Checking the checkout"
git fetch -q origin main
[ -z "$(git status --porcelain -- deploy servers scripts)" ] || die "uncommitted changes under deploy/, servers/, or scripts/. Commit or stash them first."
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "this checkout is not at origin/main. Run: git switch --detach origin/main"
if python3 -c "import json,sys; sys.exit(0 if sys.argv[1] in json.load(open('deploy/services.json')) else 1)" "$slug"; then
  die "$slug is already in deploy/services.json, so it already exists. CI deploys it from release tags."
fi
echo "OK: $slug at $(git rev-parse --short HEAD); worker $worker, container $app, domain $domain"

step "2/5  Checking Docker (needed to build the container image)"
if ! docker info >/dev/null 2>&1; then
  if command -v colima >/dev/null 2>&1; then
    echo "Starting Colima..."; colima start
  else
    echo "Starting Docker Desktop..."; open -a Docker
  fi
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
fi
docker info >/dev/null 2>&1 || die "Docker is not running. Start Colima (colima start) or Docker Desktop and rerun."
echo "OK: Docker $(docker info --format '{{.ServerVersion}}')"

step "3/5  Checking your Cloudflare login"
cd "$dir"
npm ci --ignore-scripts --no-audit --no-fund --silent
if ! npx wrangler whoami --json 2>/dev/null | grep -q "$ACCOUNT_ID"; then
  echo "A browser window will open. Sign in to Cloudflare as the 1102tools account and click Allow."
  npx wrangler login
  npx wrangler whoami --json 2>/dev/null | grep -q "$ACCOUNT_ID" || die "logged in, but not to the 1102tools Cloudflare account ($ACCOUNT_ID)"
fi
echo "OK: logged in to the 1102tools Cloudflare account"

step "4/5  Deploying $worker (builds the image, creates the container and $domain; a few minutes)"
npx wrangler deploy --env production

step "5/5  Finding the new container application and checking the service"
app_id=$(npx wrangler containers list --json 2>/dev/null | python3 -c "
import json, sys
apps = json.load(sys.stdin)
apps = apps.get('result', apps) if isinstance(apps, dict) else apps
print(next((a.get('id', '') for a in apps if a.get('name') == sys.argv[1]), ''))" "$app")
health=""
for _ in $(seq 1 30); do
  health=$(curl -fsS --max-time 20 "https://$domain/health" 2>/dev/null) && break
  sleep 10
done

printf '\n\033[1m----------------------------------------------------------------\033[0m\n'
if [ -n "$app_id" ]; then
  printf 'Container application ID for %s:\n\n    \033[32m%s\033[0m\n\n' "$app" "$app_id"
else
  echo "Could not read the application ID automatically. Run this and copy the id for $app:"
  echo "    (cd $dir && npx wrangler containers list)"
fi
if [ -n "$health" ]; then
  echo "Health check https://$domain/health:"
  echo "    $health"
else
  echo "https://$domain/health did not answer yet (the custom domain can take a few minutes)."
fi
echo
echo "Paste the application ID back to Claude to finish CI registration."
