# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in any package in this repository (`rfnry-chat-server`, `rfnry-chat-client`, or `@rfnry/chat-client-react`), please report it privately.

- Email: contact@rfnry.dev
- GitHub: open a private security advisory at https://github.com/rfnry/chat/security/advisories/new

Please include:

- The affected package(s) and version(s).
- A clear description of the issue and its impact.
- Reproduction steps or a proof-of-concept where possible.
- Whether you've disclosed the issue elsewhere.

We aim to acknowledge reports within 3 business days and to ship a fix or mitigation within 30 days for critical issues, longer for lower-severity issues. We'll credit you in the release notes unless you ask us not to.

## Supported versions

Only the latest released minor of each package is supported with security fixes during the `0.x` line. Once a `1.0.0` is published, we'll publish a longer-term support policy.

| Package | Supported |
|---|---|
| `rfnry-chat-server` | latest 0.x |
| `rfnry-chat-client` | latest 0.x |
| `@rfnry/chat-client-react` | latest 0.x |

## In scope

- Authentication / authorization bypass (e.g. `AuthenticateCallback` invariants, namespace scoping leaks).
- Tenant isolation failures — events, threads, presence, or members visible across tenants when `namespace_keys` is configured.
- Loop / amplification attacks — handler chains, mention routing, recipient resolution.
- Data exposure via the wire protocol — events leaking to non-recipients, replay covering events outside the requester's tenant scope.
- Protocol parser issues — `parse_event`, `parse_identity`, `to_event`, etc. trusting malformed input in a way that yields RCE or DOS.

## Out of scope

- Vulnerabilities in third-party dependencies that are already fixed upstream — please report those upstream first.
- DoS at the transport layer that is bounded by your own infrastructure (rate limits, WAF, load balancer). The library does not include a rate limiter; you are expected to provide one.
- Issues in example applications (`yard/examples/rfnry-chat/*`). Those are demos, not production code.

## Disclosure timeline

- Day 0: Report received, acknowledged.
- Day 1–14: Triage, reproduction, fix scoped.
- Day 14–30: Patch released, advisory published with credits.
- Day 30+ (if needed): Coordinated disclosure with downstream packagers.
