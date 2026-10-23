// Command caddy is Caddy with only the modules the Caddyfile uses.
//
// It replaces modules/standard, which registers every standard module: acme
// server, fastcgi, basic auth, tracing, metrics, push and so on. A module that
// is not linked cannot be configured, by mistake or otherwise.
//
// The HTTP and TLS apps, static_response (respond, redir), subroute and the
// matchers come in through caddyhttp, which the modules below import.
//
// To add a module, import it here, then update modules.txt (see build.sh).
package main

import (
	caddycmd "github.com/caddyserver/caddy/v2/cmd"

	// The Caddyfile adapter.
	_ "github.com/caddyserver/caddy/v2/caddyconfig/caddyfile"
	// file_server, and the file matcher behind try_files.
	_ "github.com/caddyserver/caddy/v2/modules/caddyhttp/fileserver"
	// header.
	_ "github.com/caddyserver/caddy/v2/modules/caddyhttp/headers"
	// reverse_proxy.
	_ "github.com/caddyserver/caddy/v2/modules/caddyhttp/reverseproxy"
	// rewrite and try_files.
	_ "github.com/caddyserver/caddy/v2/modules/caddyhttp/rewrite"
	// The console and json log encoders, and the log writers.
	_ "github.com/caddyserver/caddy/v2/modules/logging"
)

func main() {
	caddycmd.Main()
}
