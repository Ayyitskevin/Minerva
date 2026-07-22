# Security policy

## Milestone 1 support boundary

Minerva is an alpha, single-OS-user local application tested on Linux/POSIX with
Python 3.12–3.14. Other operating systems are not currently verified or supported.
It binds to `127.0.0.1` by default. Loopback restrictions and CSRF reduce
browser-origin risk; they are not authentication and do not isolate mutually
untrusted processes running as the same OS user. Do not expose the server through a
reverse proxy, tunnel, container port publish, or non-loopback bind.

Source snapshots and research databases can contain sensitive material. Protect the
database and export directory with OS permissions and backups. Secret-pattern scanning
is defense in depth, not a substitute for reviewing material before import. Milestone
1 does not encrypt storage or exports.

Append-only triggers, digests, doctor, and export detect partial or inconsistent
tampering. They are not an external signature or trust anchor: a determined process
inside the same OS-user boundary can coordinate changes to content and integrity
metadata. Standalone backups must therefore be protected and versioned outside the
working database when recovery assurance matters.

There is no URL fetching, model invocation, code/notebook execution, plugin loading,
publication, or messaging surface. URL values are inert metadata.

## Reporting a vulnerability

Do not include source contents, database files, credentials, private paths, or working
exploits in a public issue. Use GitHub private vulnerability reporting for this
repository when available, or contact the repository owner through an already trusted
private channel. Include the affected version, a minimal synthetic reproduction, and
impact. No service-level response time is promised during alpha development.

## Supported versions

Until the first stable release, only the latest commit on the maintained branch is
eligible for security fixes. No released version is currently supported for remote or
multi-user operation.
