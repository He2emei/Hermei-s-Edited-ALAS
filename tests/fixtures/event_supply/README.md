# CN event free-pack evidence

These are dated user-account screenshots from 2026-10-24, not a claim that a
new purchase was made by these tests. Listing, home, preview and confirmation
fixtures come from `code_workflow/evidence/2026-10-24-evening-care`.

`confirm-evidence.png` is the actual INFORMATION / 0-diamond confirmation,
originally named `alas2-free-III-zero-price-preview-buy.png`. Similarly named
`free-III-confirm-0.png` is a GET_ITEMS result and must not be used as a
confirmation-button fixture. Test arrays use RGB, as native `device.image` does.

Runtime Button assets live under `assets/cn/freebies` on a 1280x720 canvas;
Button loads its absolute `area` from that canvas. A cropped label used directly
by `claim_label_matches` is intentionally a small RGB image.
