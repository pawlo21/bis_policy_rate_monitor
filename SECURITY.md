# Security policy

## Supported versions

This project is delivered as part of an interview exercise and does not yet
publish formal release versions. The `master` branch is the only supported
version. Security fixes will land directly on `master`.

## Reporting a vulnerability

If you believe you have found a security issue in this code, **please do not
open a public GitHub issue**. Instead:

- Use GitHub's private vulnerability reporting (Security tab → "Report a
  vulnerability") if it is enabled on the repository, **or**
- Email **pawlo.gom@gmail.com** with subject prefix `[bis-prates security]`.

Please include:

- A description of the issue and the affected file/function.
- Steps to reproduce, ideally a minimal example.
- The version (commit SHA) you observed it on.
- Any suggested mitigation, if you have one in mind.

## What to expect

- Acknowledgement within **3 working days**.
- An initial assessment within **7 working days**.
- A fix or written rationale for not fixing within **30 days** for confirmed
  issues.

## Scope

This repository is a small data-processing CLI. Issues that fall in scope
include but are not limited to:

- Vulnerabilities in how the BIS bulk archive is downloaded, validated, or
  unpacked (path traversal in ZIPs, SSRF via the bulk-download URL, etc.).
- Untrusted-input handling in the SDMX metadata flow.
- Vulnerabilities in dependencies that this project pins or surfaces.

Out of scope: theoretical issues with no demonstrated exploit path,
denial-of-service requiring control of the BIS endpoints themselves, and
issues that require an attacker who already has shell access to the host
running the tool.

## Coordination

If a fix requires coordinated disclosure with upstream BIS endpoints or
with `pysdmx` / `gingado`, that will be done before public disclosure.
