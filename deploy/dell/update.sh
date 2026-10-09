#!/usr/bin/env bash
# Builds and restarts a Dell MCP server when a newer release tag covers it.
# The Dell runs the same commit as the Cloudflare container: the newest `v*`
# or `<slug>/v*` tag, which is what publish-pypi.yml releases. Usage:
#   update.sh [slug ...]       (default: all five)
set -euo pipefail
ROOT=/opt/mcp-origin
REPO=$ROOT/repo
LABEL=org.1102tools.release-sha
slugs=(usaspending ecfr federal-register gsa-calc regulations-gov)
(($#)) && slugs=("$@")

git -C "$REPO" fetch -q --tags --force origin
built=()
for slug in "${slugs[@]}"; do
  tag=$(git -C "$REPO" for-each-ref --sort=-creatordate --count=1 \
    --format='%(refname:short)' 'refs/tags/v*' "refs/tags/$slug/")
  sha=$(git -C "$REPO" rev-parse "$tag^{commit}")
  live=$(docker image inspect -f "{{index .Config.Labels \"$LABEL\"}}" "mcp-origin/$slug:live" 2>/dev/null || true)
  [[ $live == "$sha" ]] && continue

  echo "$slug: building $tag ($sha)"
  src=$ROOT/src/$slug
  rm -rf "$src" && mkdir -p "$src"
  git -C "$REPO" archive "$sha" | tar -x -C "$src"
  docker build -q --build-arg RELEASE_SHA="$sha" --label "$LABEL=$sha" \
    -f "$src/deploy/$slug/Dockerfile" -t "mcp-origin/$slug:$sha" -t "mcp-origin/$slug:live" "$src" >/dev/null
  built+=("$slug:$sha")
done
((${#built[@]})) || exit 0

# Recreates only the services whose image changed.
docker compose -f "$ROOT/compose.yaml" up -d --quiet-pull
for entry in "${built[@]}"; do
  slug=${entry%%:*} sha=${entry#*:} health=
  for _ in $(seq 30); do
    health=$(curl -s -m 5 -H "Host: $slug-origin.1102tools.com" http://127.0.0.1:8790/health || true)
    [[ $health == *"$sha"* ]] && break
    sleep 2
  done
  [[ $health == *"$sha"* ]] || { echo "$slug: not healthy on $sha" >&2; exit 1; }
  echo "$slug: live on $sha"
  docker image ls --format '{{.Tag}}' "mcp-origin/$slug" | grep -vxE "live|$sha" \
    | sed "s|^|mcp-origin/$slug:|" | xargs -r docker image rm -f >/dev/null
done
