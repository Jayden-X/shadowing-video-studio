# Security & Local Data Standard

## Local-first does not mean security-free

Private repositories and local execution do not justify committing credentials or user data.

## Secrets

Never commit:

- API keys
- access tokens
- passwords
- private keys
- provider credential files

Use local environment/config files excluded by Git.

Committed example configuration must contain placeholders only.

## User content

Treat user-provided:

- dialogue
- background images
- generated audio/video
- local project history

as runtime data, not repository content, unless a deliberately synthetic fixture is created.

## Logging

Do not log:

- secrets
- authorization headers
- raw credential-bearing configuration

Avoid logging full user content by default when metadata is sufficient.

## External AI providers

Before sending content to an external provider:

- the provider must be explicitly selected/configured
- requests should contain only data required for the feature
- credentials remain local
- failures must not destroy the original source data

## Control adapter boundaries

Keep human-review secrets outside AI protocol tools: do not return approval nonces,
accept a tool-supplied approval flag, or expose a tool that approves its own generation
request. State the trusted-local-process boundary explicitly; a browser nonce is not
isolation from another process owned by the same Mac user.

Sanitize errors at the protocol boundary as well as inside handlers. SDK input-validation
failures may echo submitted dialogue before a handler runs; return a safe input error
instead of forwarding those diagnostics.

## Filesystem safety

Generated output and temporary files must use known application-controlled locations.

Avoid arbitrary delete operations.

When cleanup is required, scope it to files created and owned by the application.

## Dependency safety

Do not introduce obscure dependencies for trivial functionality.

Pin or constrain important runtime dependencies consistently with project policy.

## Security findings

Security/data-loss issues are Blockers in review and must not be deferred as ordinary polish.
