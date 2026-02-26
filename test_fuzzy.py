import difflib

def is_duplicate(new_line, existing_lines):
    new_norm = new_line.replace(" ", "").lower()
    trans = str.maketrans("abcehopxyM", "авсенорхум")
    new_norm = new_norm.translate(trans)
    
    for ex in existing_lines:
        ex_norm = ex.replace(" ", "").lower().translate(trans)
        
        # Substring match
        if new_norm in ex_norm or ex_norm in new_norm:
            return True, ex
            
        # Fuzzy match
        ratio = difflib.SequenceMatcher(None, new_norm, ex_norm).ratio()
        if ratio > 0.75:
            return True, ex
            
    return False, None

existing = ["на работу системы"]
print(is_duplicate("Ha раб системы.", existing))
print(is_duplicate("a ie \ ‚м", existing))
print(is_duplicate("NALie ЛЕ i]", existing))

