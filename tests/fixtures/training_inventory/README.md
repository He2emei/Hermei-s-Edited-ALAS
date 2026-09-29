CN 1280x720 material inventory screenshots captured on 2026-09-10.
Only the item grid is retained; surrounding account and navigation UI is blanked.

- page3: four gold T3 retrofit blueprint types.
- page6: T2 experience books, which must not match the T1 template.
- page7: T1 experience books.
- material-absent-battleship: the `alas` account's own T3 blueprint row, captured
  live on 2026-09-30 01:0x while the Hard task was crash-looping. The row holds
  驱逐改造图纸T3 (13), 巡洋改造图纸T3 (2) and 航母改造图纸T3 (9) in adjacent
  columns with **no cell at all** between 巡洋 and 航母: the account owns no
  战列改造图纸T3, and the CN material page only lists items the account owns.
  The `battleship` template scores 0.513 on 巡洋's cell, i.e. it is absent rather
  than unrecognized.

These fixtures verify template recognition independently of OCR count mocks.
