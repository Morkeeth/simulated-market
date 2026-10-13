"""An explicitly disabled service, not a local fixture or a runtime call."""


class DisabledGrounding:
    name = 'none-requested'
    label = 'NONE'
    items_source = 'no search requested; no external grounding service ran'

    def items(self): return []
    def for_topic(self, topic): return None
    def record(self, query, receipts_path=None): return None
