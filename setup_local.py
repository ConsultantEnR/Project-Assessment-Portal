#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_local.py
Telecharge toutes les dependances externes (JS, polices) et met a jour
tous les fichiers HTML pour que l'app tourne entierement en local.
"""
import os, re, sys, urllib.request
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE  = os.path.dirname(os.path.abspath(__file__))
LIBS  = os.path.join(BASE, 'libs')
FONTS = os.path.join(BASE, 'fonts')
os.makedirs(LIBS,  exist_ok=True)
os.makedirs(FONTS, exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'

def dl(url, dest, label=None):
    label = label or os.path.basename(dest)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f'  [déjà présent] {label}')
        return True
    print(f'  Téléchargement : {label} ...', end='', flush=True)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        with open(dest, 'wb') as f:
            f.write(data)
        print(f' OK ({len(data)//1024} Ko)')
        return True
    except Exception as e:
        print(f' ERREUR : {e}')
        return False

# ── 1. Bibliothèques JS ───────────────────────────────────────────────────────
print('\n── Bibliothèques JS ─────────────────────────────')
JS = [
    ('https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js',     'chart.umd.min.js'),
    ('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js',      'pdf.min.js'),
    ('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js','pdf.worker.min.js'),
    ('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js',       'jszip.min.js'),
    ('https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js',         'xlsx.full.min.js'),
]
for url, name in JS:
    dl(url, os.path.join(LIBS, name))

# ── 2. Polices Google Fonts ───────────────────────────────────────────────────
print('\n── Google Fonts ──────────────────────────────────')
GFONTS_URL = (
    'https://fonts.googleapis.com/css2'
    '?family=Teko:wght@300;400;500;600;700'
    '&family=Montserrat:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300;1,400'
    '&family=Poppins:wght@300;400;500;600'
    '&display=swap'
)
try:
    req = urllib.request.Request(GFONTS_URL, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        css = r.read().decode('utf-8')

    font_urls = list(dict.fromkeys(re.findall(r'url\((https://fonts\.gstatic\.com/[^)]+)\)', css)))
    print(f'  {len(font_urls)} fichiers de polices trouvés')

    for furl in font_urls:
        fname = re.sub(r'[?&].*', '', furl.split('/')[-1])  # nom propre sans query string
        dest  = os.path.join(FONTS, fname)
        dl(furl, dest, fname)
        css = css.replace(furl, f'fonts/{fname}')

    css_path = os.path.join(FONTS, 'fonts.css')
    with open(css_path, 'w', encoding='utf-8') as f:
        f.write(css)
    print(f'  [OK] fonts.css écrit')

except Exception as e:
    print(f'  ERREUR Google Fonts : {e}')
    print('  Les polices resteront chargées depuis Google CDN.')

# ── 3. Mise à jour des fichiers HTML ──────────────────────────────────────────
print('\n── Mise à jour des fichiers HTML ─────────────────')

# Ordre important : preconnect avant stylesheet pour éviter les doublons
SUBS = [
    # Supprimer la ligne preconnect Google Fonts
    (r'[ \t]*<link[^>]+rel=["\']preconnect["\'][^>]+fonts\.googleapis\.com[^>]*>\n?', ''),
    # Supprimer la ligne preconnect gstatic (parfois présente)
    (r'[ \t]*<link[^>]+rel=["\']preconnect["\'][^>]+fonts\.gstatic\.com[^>]*>\n?', ''),
    # Remplacer le lien stylesheet Google Fonts
    (r'<link[^>]+href=["\']https://fonts\.googleapis\.com/css2[^"\']*["\'][^>]*>',
     '<link rel="stylesheet" href="fonts/fonts.css">'),
    # Chart.js (toutes versions)
    (r'https://cdn\.jsdelivr\.net/npm/chart\.js@[^/\'"]*/dist/chart\.umd\.min\.js',
     'libs/chart.umd.min.js'),
    # XLSX jsdelivr
    (r'https://cdn\.jsdelivr\.net/npm/xlsx@[^/\'"]*/dist/xlsx\.full\.min\.js',
     'libs/xlsx.full.min.js'),
    # XLSX cdnjs
    (r'https://cdnjs\.cloudflare\.com/ajax/libs/xlsx/[^/\'"]*/xlsx\.full\.min\.js',
     'libs/xlsx.full.min.js'),
    # PDF.js
    (r'https://cdnjs\.cloudflare\.com/ajax/libs/pdf\.js/[^/\'"]*/pdf\.min\.js',
     'libs/pdf.min.js'),
    # PDF.js worker (dans les <script> src ET dans les variables JS)
    (r'https://cdnjs\.cloudflare\.com/ajax/libs/pdf\.js/[^/\'"]*/pdf\.worker\.min\.js',
     'libs/pdf.worker.min.js'),
    # JSZip
    (r'https://cdnjs\.cloudflare\.com/ajax/libs/jszip/[^/\'"]*/jszip\.min\.js',
     'libs/jszip.min.js'),
]

html_files = sorted(f for f in os.listdir(BASE) if f.endswith('.html'))
changed = 0
for fname in html_files:
    path = os.path.join(BASE, fname)
    with open(path, 'r', encoding='utf-8') as f:
        original = f.read()
    content = original
    for pattern, repl in SUBS:
        content = re.sub(pattern, repl, content)
    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'  [modifié]  {fname}')
        changed += 1
    else:
        print(f'  [inchangé] {fname}')

print(f'\n  {changed} fichier(s) mis à jour.')

# ── 4. Résumé ─────────────────────────────────────────────────────────────────
print('\n═══════════════════════════════════════════════════')
print(' Configuration locale terminée.')
print(' Lance l\'app avec : lancer_app.bat')
print('═══════════════════════════════════════════════════\n')
