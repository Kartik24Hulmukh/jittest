# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.3.5   | :white_check_mark: |
| < 0.3.5 | :x:                |

## Reporting a Vulnerability

We take the security of `jittest` seriously. Because `jittest` is designed to run in automated CI environments and verify untrusted pull requests in sandboxed containers, vulnerabilities involving sandbox escapes, signature forgeries, or unverified command execution are treated as critical.

If you discover a security vulnerability in `jittest`, please report it privately:

1. **GitHub Security Advisory**: Open a draft security advisory at [https://github.com/Kartik24Hulmukh/jittest/security/advisories/new](https://github.com/Kartik24Hulmukh/jittest/security/advisories/new).
2. **Email**: Contact `security@jittest.org` (or the repository maintainers).

Please do **NOT** file public GitHub issues for security vulnerabilities.

### What to Include in Your Report

- A clear description of the vulnerability and its potential impact.
- Exact reproduction steps, proof of concept (PoC), or test case.
- The versions of `jittest`, Python, and OS / container runtime affected.
- Any proposed remediation or patch if available.

### Response Timeline

- **Initial Response**: Within 48 hours of report receipt.
- **Triage & Reproduction**: Within 5 business days.
- **Patch Release & Disclosure**: Coordinated disclosure within 30 days of confirmed fix.
