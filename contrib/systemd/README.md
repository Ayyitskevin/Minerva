# systemd examples

These units are examples, not a deploy. Copy them out of the checkout and fill
local paths. Do not commit a filled-in unit: it would put private paths into
git.

`minerva serve` refuses any host other than `127.0.0.1`. Do not "fix" that
here. Tailscale, reverse proxies, and public binds remain out of season.
