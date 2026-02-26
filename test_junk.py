import re

lines = [
    "Гарантия 60 днеи”",
    "на работу системы.",
    "Все критические",
    "ошибки исправим",
    "бесплатно.",
    "a ie \ ‚м",
    "NALie ЛЕ i]",
    "Ha раб системы."
]

def is_junk(line: str) -> bool:
    chars = line.replace(" ", "")
    if not chars:
        return True
    letters = len(re.findall(r'[а-яА-Яa-zA-Z]', chars))
    if letters < 3:
        return True
    if letters / len(chars) < 0.5:
        return True
    words = re.findall(r'[а-яА-Яa-zA-Z]+', line)
    
    # Needs at least one word of 4+ letters OR multiple 3-letter words
    long_words = sum(1 for w in words if len(w) >= 3)
    if long_words == 0 and not any(len(w) >= 4 for w in words):
        return True
        
    weird = len(re.findall(r'[^а-яА-Яa-zA-Z0-9\s.,!?:\-]', line))
    if weird > 2:
        return True
    
    # NALie ЛЕ i] has weird=1 (the ]). 
    # Let's count uppercase vs lowercase in words?
    # Actually, a line with mostly english letters but Cyrillic script config usually means hallucination.
    
    return False

for line in lines:
    print(f"{line!r:30} -> {is_junk(line)}")
