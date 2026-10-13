"""Bounded content guard, separate from a model's screen agreement.

Not a general semantic oracle. A quoted navigation label cannot demonstrate a
read result. Pricing reads additionally need an explicit price/free/sales answer.
"""
import re

CONTENT_JS = """() => {
 const root=(document.querySelector('main,[role=main],article')||document.body).cloneNode(true);
 root.querySelectorAll('nav,header,footer,script,style,button,form,[role=navigation]').forEach(e=>e.remove());
 root.querySelectorAll('a').forEach(e=>e.remove());
 return root.textContent.replace(/\\s+/g,' ').trim();
}"""
PRICING_TASK = re.compile(r'\b(price|prices|pricing|cost|costs|subscription|tarif|prix|co[uû]t)\b', re.I)
PRICE_ANSWER = re.compile(r'(?:[$€£]\s*\d|\d[\d.,]*\s*(?:USD|EUR|GBP|dollars?|euros?)\b|\bfree\b|\bcontact\s+(?:our\s+)?sales\b|\bgratuit\b)', re.I)


def check(task, evidence, content, http_status=None):
    if http_status is not None and not 200 <= http_status < 400:
        return False, 'The final page did not load successfully.'
    quote = re.sub(r'\s+', ' ', evidence or '').strip('"\'“”.… ')
    text = re.sub(r'\s+', ' ', content or '')
    if len(quote) < 12 or quote not in text:
        return False, 'The quoted answer is absent from page content; navigation alone is insufficient.'
    pricing_only = PRICING_TASK.search(task or '') and not re.search(r'\bor\b.*\b(?:how|works|under the hood)\b', task or '', re.I)
    if pricing_only and not PRICE_ANSWER.search(quote):
        return False, 'The quoted content does not state a price, free access or a contact-sales answer.'
    return True, ''
