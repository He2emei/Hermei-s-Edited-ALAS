# CN weekly supply-pack evidence

Selected and unselected navigation samples are actual 2026-10-28 account2
frames. They distinguish the current 优惠礼包 row from 茗的精选. The 400-diamond
preview is an actual account1 read-only view that was cancelled, with no purchase.

The zero-preview and zero-confirmation samples use the shared purchase dialog
from the 2026-10-24 event reward. They test amount/name/control recognition and
are not evidence of a successful weekly-pack purchase. The weekly pack had
already been claimed manually on both accounts when this fix was investigated.

The real confirmation source is `alas2-free-III-zero-price-preview-buy.png` in
`code_workflow/evidence/2026-10-24-evening-care`. A similarly named
`free-III-confirm-0.png` actually shows GET_ITEMS. Native screenshots and tests
use RGB. Button runtime images must retain the native 1280x720 coordinate canvas.
