# Security policy

## Supported version

Security fixes target the current `master` branch. This research-backed library is pre-1.0; users should follow the default branch rather than expect support for older snapshots.

## Reporting

Please use GitHub's private vulnerability reporting for security-sensitive findings. If that option is unavailable, open a minimal issue that does not include exploit details and ask for a private contact channel.

Do not include credentials, unpublished publisher content, or private network details in a report.

## Outbound request boundary

`ArticleExtractor` accepts remote URLs, so server-side request forgery is part of its threat model. The default client:

- accepts only `http` and `https` URLs without embedded credentials;
- rejects port zero and private, loopback, link-local, shared, documentation, benchmark, reserved, site-local, multicast, and unspecified destinations using explicit version-stable network tables;
- recursively checks IPv4-mapped, 6to4, Teredo, well-known NAT64, and both ISATAP interface-ID forms instead of trusting only the outer IPv6 address;
- limits synchronous DNS work to eight process-wide resolver threads shared across clients; capacity waits consume the same absolute deadline and saturation fails closed;
- validates every redirect and blocks HTTPS-to-HTTP downgrades;
- pins each vetted DNS answer to the socket while retaining TLS hostname verification;
- accepts only HTML/XHTML, identity encoding, bounded bodies, and bounded redirects;
- applies one monotonic wall-clock deadline to DNS, all redirect resolutions and address attempts, TCP/TLS connection, request transmission, headers, and body reads, so progress-by-drip cannot extend the configured timeout.

Active library, CLI, backlog, and live-validation diagnostics remove URL user information, query strings, and fragments before display. Human-readable output strips C0/C1 and ANSI/ESC control sequences from publisher text. The advertised backlog viewer constructs cards with DOM `textContent` and makes only validated `http:` or `https:` URLs clickable; JSON output remains machine-readable and escaped with `json.dumps`/`JSON.parse`.

`allow_private_networks=True` and the CLI's `--allow-private-network` option deliberately relax the address policy for trusted internal use. Do not enable either for untrusted user input.

HTML extraction is heuristic. Treat returned text and metadata as untrusted content: escape it for its destination and do not execute embedded markup.
