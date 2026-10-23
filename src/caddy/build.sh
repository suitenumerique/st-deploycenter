#!/bin/sh
# Builds Caddy from this directory. The frontend Dockerfile and
# bin/scalingo_postfrontend both run it, so the build flags live here only.
#
# Usage: build.sh OUTPUT
# GOOS and GOARCH are honoured to cross-compile.
set -eu

out="${1:?usage: build.sh OUTPUT}"
cd "$(dirname "$0")"

# The toolchain is the go directive of go.mod, never an automatic download.
export GOTOOLCHAIN=local
want="go$(awk '$1 == "go" { print $2 }' go.mod)"
have="$(go env GOVERSION)"
if [ "$have" != "$want" ]; then
  echo "build.sh: go.mod wants $want but the toolchain is $have" >&2
  exit 1
fi

# CGO stays off: the result has to run on distroless. The tags leave out code
# nothing here can reach:
# - nobadger, nomysql, nopgx, nobbolt: database drivers linked through
#   smallstep's storage layer, used only by an ACME server we do not build.
# - grpcnotrace: x/net/trace, which gRPC (via OpenTelemetry) would link.
# - nethttpomithttp2: the standard library's HTTP/2. The Caddyfile sets
#   `protocols h1`; any config that enables h2 makes Caddy panic at startup.
CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' \
  -tags nobadger,nomysql,nopgx,nobbolt,grpcnotrace,nethttpomithttp2 \
  -o "$out" .

# Fail the build rather than the deployment if the module set is not exactly
# modules.txt: a module that did not make it in, or one that came in with a
# dependency upgrade. Regenerate it with the same pipeline, but only after
# reviewing what changed. A cross-compiled binary cannot run here, but the set
# does not depend on the architecture, so the native builds cover it.
if [ "$(go env GOOS)/$(go env GOARCH)" = "$(go env GOHOSTOS)/$(go env GOHOSTARCH)" ]; then
  "$out" list-modules | grep '^[a-z]' | LC_ALL=C sort | diff modules.txt -
else
  echo "build.sh: cross-compiling, module set not checked" >&2
fi
