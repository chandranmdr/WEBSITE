#!/usr/bin/env python3
"""
apply_hamburger_menu.py
=======================
Applies the updated hamburger menu (from conditions.html) to all other
HTML files in the chandranmdr/WEBSITE repository.
"""

import re
import os
import shutil
from pathlib import Path

# Files to update (conditions.html is the source of truth, skip it)
FILES = [
    "index.html",
    "hip-replacement.html",
    "hip-resurfacing.html",
    "knee-replacement.html",
    "revision-surgery.html",
    "faq.html",
    "fees.html",
    "testimonials.html",
    "book-consultation-6.html",
]

# The CORRECT button HTML (from conditions.html)
NEW_BUTTON = '''<button class="nav-mobile" id="mobileToggle" aria-label="Open menu">
<svg class="icon-menu" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
<svg class="icon-close" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke-width="2" style="display:none"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
</button>'''

# The CORRECT JavaScript block (from conditions.html)
NEW_JS_TOGGLE = '''// Hamburger ↔ X toggle
document.getElementById('mobileToggle').addEventListener('click',function(){
const isOpen = document.getElementById('navLinks').classList.toggle('show');
this.querySelector('.icon-menu').style.display = isOpen ? 'none' : 'block';
this.querySelector('.icon-close').style.display = isOpen ? 'block' : 'none';
this.setAttribute('aria-label', isOpen ? 'Close menu' : 'Open menu');
});

// Procedures dropdown on mobile
const dropdown = document.querySelector('.nav-dropdown > a');
if(dropdown){
dropdown.addEventListener('click',function(e){
if(window.innerWidth<=768){
e.preventDefault();
this.parentElement.classList.toggle('open');
}
});
}'''  

# CSS patch for .nav-mobile
NEW_NAV_MOBILE_CSS = '.nav-mobile{display:none;background:none;border:none;cursor:pointer;padding:8px}\n.nav-mobile svg{stroke:var(--navy)}'

def patch_file(filepath: str) -> tuple[bool, list[str]]:
    path = Path(filepath)
    if not path.exists():
        return False, [f"  ✗ File not found: {filepath}"]

    original = path.read_text(encoding="utf-8")
    html = original
    notes = []

    # 1. Add id="navLinks" to the nav-links ul if missing
    if 'id="navLinks"' not in html and 'id=\'navLinks\'' not in html:
        old_ul = re.search(r'<ul class="nav-links"([^>]*)>', html)
        if old_ul:
            replacement = f'<ul class="nav-links" id="navLinks"{old_ul.group(1)}>'
            html = html.replace(old_ul.group(0), replacement, 1)
            notes.append("  ✓ Added id=\"navLinks\" to <ul class=\"nav-links\">")

    # 2. Replace old button with new two-SVG button
    pattern_a = re.compile(
        r'<button class="mobile-toggle"[^>]*>[\s\S]*?<span></span><span></span><span></span>[\\s\S]*?</button>',
        re.DOTALL
    )
    pattern_b = re.compile(
        r'<button class="nav-mobile"[^>]*>[\\s\S]*?</button>',
        re.DOTALL
    )

    if pattern_a.search(html):
        html = pattern_a.sub(NEW_BUTTON, html, count=1)
        notes.append("  ✓ Replaced mobile-toggle button (3-span style) with new icon-swap button")
    elif pattern_b.search(html):
        match = pattern_b.search(html)
        if match and 'icon-menu' not in match.group(0):
            html = pattern_b.sub(NEW_BUTTON, html, count=1)
            notes.append("  ✓ Replaced old nav-mobile button (single SVG) with new icon-swap button")

    # 3. Fix CSS
    html = re.sub(r'\.mobile-toggle\{[^}]+\}', '.nav-mobile{display:none;background:none;border:none;cursor:pointer;padding:8px}', html)
    css_pattern = re.compile(r'\.nav-mobile\{[^}]+\}(?:\s*\.nav-mobile\s+svg\{[^}]+\})?')
    if css_pattern.search(html):
        html = css_pattern.sub(NEW_NAV_MOBILE_CSS, html, count=1)
        notes.append("  ✓ Updated .nav-mobile CSS")

    # 4. Replace old JS toggle logic
    old_js_patterns = [
        re.compile(r"//\s*(?:Mobile\s+)?(?:hamburger|nav|menu|toggle)[^\n]*\n"
                   r"document\.(?:getElementById|querySelector)[^\n]+\.addEventListener[^\n]+\n"
                   r"(?:.*\n)*?.*classList\.toggle\('show'\)[^\n]*\n"
                   r"(?:.*\n)*?}\);", re.IGNORECASE),
        re.compile(r"document\.getElementById\('mobileToggle'\)\.addEventListener\('click'[^\s\S]*?}\);", re.DOTALL),
    ]

    js_replaced = False
    for pat in old_js_patterns:
        if pat.search(html):
            html = pat.sub('__HAMBURGER_JS_PLACEHOLDER__', html, count=1)
            for p2 in old_js_patterns:
                html = p2.sub('', html)
            html = html.replace('__HAMBURGER_JS_PLACEHOLDER__', NEW_JS_TOGGLE, 1)
            notes.append("  ✓ Replaced JS toggle block")
            js_replaced = True
            break

    if not js_replaced:
        if '</script>' in html:
            html = html.replace('</script>', f'\n{NEW_JS_TOGGLE}\n</script>', 1)
            notes.append("  ✓ Injected new JS toggle block before </script>")

    # 5. Write back if changed
    if html != original:
        shutil.copy2(path, path.with_suffix('.html.bak'))
        path.write_text(html, encoding="utf-8")
        return True, notes
    else:
        notes.append("  – No changes made (already up to date?)")
        return False, notes

def main():
    print("=" * 60)
    print("  Hamburger Menu Patcher — chandranmdr/WEBSITE")
    print("=" * 60)
    print()

    changed_count = 0
    for f in FILES:
        print(f"Processing: {f}")
        changed, notes = patch_file(f)
        for note in notes:
            print(note)
        if changed:
            changed_count += 1
            print(f"  → Saved (backup: {f}.bak)")
        print()

    print("=" * 60)
    print(f"  Done. {changed_count}/{len(FILES)} files updated.")
    print("=" * 60)

if __name__ == "__main__":
    main()