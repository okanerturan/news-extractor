# Security policy

## Supported version

Security fixes target the current `master` branch. This research-backed library is pre-1.0; users should follow the default branch rather than expect support for older snapshots.

## Reporting

Please use GitHub's private vulnerability reporting for security-sensitive findings. If that option is unavailable, open a minimal issue that does not include exploit details and ask for a private contact channel.

Do not include credentials, unpublished publisher content, or private network details in a report.

## Outbound request boundary

`ArticleExtractor` accepts remote URLs, so server-side request forgery is part of its threat model. The default client:

- accepts only `http` and `https` URLs without embedded credentials;
- rejects private, loopback, link-local, reserved, multicast, and unspecified destinations;
- validates every redirect and blocks HTTPS-to-HTTP downgrades;
- pins each vetted DNS answer to the socket while retaining TLS hostname verification;
- accepts only HTML/XHTML, identity encoding, bounded bodies, bounded redirects, and configured timeouts.

`allow_private_networks=True` and the CLI's `--allow-private-network` option deliberately relax the address policy for trusted internal use. Do not enable either for untrusted user input.

HTML extraction is heuristic. Treat returned text and metadata as untrusted content: escape it for its destination and do not execute embedded markup.
