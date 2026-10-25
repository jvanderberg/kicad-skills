#!/usr/bin/env python3
"""Fetch a datasheet and find things in it, without grepping page by page.

  datasheet.py fetch URL OUT.pdf                    # refuses anything that is not a PDF (checks the %PDF magic)
  datasheet.py find DS.pdf "Layout Example" ["Figure 36" ...] [--context 1]
  datasheet.py page DS.pdf N OUT.png [--dpi 170] [--label "Figure 12-1 layout example"]
                                                    # render one page; --label records what it shows in INDEX.md
  datasheet.py index DIR                            # every image in a reference folder is named in its INDEX.md

fetch: manufacturer "symlink" URLs and distributor datasheet links can return an HTML page instead of the PDF - a
landing page, a login wall, or a "not found" page for a discontinued part (that itself is a lifecycle warning: check
the product page). The download is kept only if it starts with %PDF.
find: prints every page whose text contains each phrase (case-insensitive, whitespace-insensitive), with the matching
line, so you can name the page that holds a figure or section (e.g. "datasheet-p30.png = Figure 36, layout example")
in the project's reference notes. pdftotext's font warnings are suppressed.
page --label: appends (or updates) a row in INDEX.md next to the PNG - file, source PDF, page, what it shows - so a
reference folder says which file holds the figure (a folder with p28 and p29 and no note sent a later session to the
documentation-support page instead of the layout example). index: lists images with no INDEX.md row and rows whose
file is gone; exit 1 if either. Needs poppler (pdftotext, pdftoppm, pdfinfo).
"""
import argparse, os, re, shutil, subprocess, sys, urllib.error, urllib.request


def fetch(url, out):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        data, status, ctype = r.read(), r.status, r.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e:
        data, status, ctype = e.read(), e.code, e.headers.get('Content-Type', '')
    if not data.startswith(b'%PDF'):
        title = re.search(rb'<title>(.*?)</title>', data, re.I | re.S)
        sys.exit('not a PDF: HTTP %s, %s%s - nothing saved. Find the real PDF link on the product page.' % (
            status, ctype or 'no content type', ', page title "%s"' % title.group(1).decode('utf-8', 'replace').strip()[:80] if title else ''))
    open(out, 'wb').write(data)
    print('saved %s (%d bytes)' % (out, len(data)))


def pages(pdf):
    n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', pdf], capture_output=True, text=True).stdout).group(1))
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True, errors='replace').stdout
    pp = txt.split('\f')
    return pp[:n] if len(pp) >= n else pp


def find(pdf, phrases, context):
    pp = pages(pdf)
    norm = lambda s: re.sub(r'\s+', ' ', s).lower()
    for ph in phrases:
        hits = []
        for i, p in enumerate(pp, 1):
            lines = p.splitlines()
            for j, line in enumerate(lines):
                if norm(ph) in norm(line):
                    ctx = lines[max(0, j - context):j + context + 1]
                    hits.append((i, ' | '.join(l.strip() for l in ctx if l.strip())[:160]))
        print('"%s": %s' % (ph, 'pages ' + ', '.join(sorted({str(h[0]) for h in hits}, key=int)) if hits else 'not found'))
        for i, s in hits[:12]:
            print('  p%-3d %s' % (i, s))


def page(pdf, n, out, dpi, label=None):
    base = os.path.splitext(out)[0]
    subprocess.run(['pdftoppm', '-r', str(dpi), '-f', str(n), '-l', str(n), '-png', '-singlefile', pdf, base], check=True)
    print(base + '.png')
    if label:
        idx = os.path.join(os.path.dirname(os.path.abspath(base)), 'INDEX.md')
        rows = read_index(idx)
        rows[os.path.basename(base) + '.png'] = (os.path.basename(pdf), str(n), label)
        write_index(idx, rows)
        print('recorded in %s: %s = %s p%d, %s' % (idx, os.path.basename(base) + '.png', os.path.basename(pdf), n, label))


HEAD = ['# Reference images', '', 'Which file shows what (written by datasheet.py page --label).', '',
        '| File | Source | Page | Shows |', '|---|---|---|---|']


def read_index(idx):
    rows = {}
    if os.path.exists(idx):
        for line in open(idx):
            m = re.match(r'^\| ([^|]+?) \| ([^|]*?) \| ([^|]*?) \| (.*?) \|\s*$', line)
            if m and m.group(1) not in ('File', '---'):
                rows[m.group(1)] = (m.group(2), m.group(3), m.group(4))
    return rows


def write_index(idx, rows):
    lines = HEAD + ['| %s | %s | %s | %s |' % (f, *rows[f]) for f in sorted(rows)]
    open(idx, 'w').write('\n'.join(lines) + '\n')


def index(d):
    rows = read_index(os.path.join(d, 'INDEX.md'))
    imgs = sorted(f for f in os.listdir(d) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.svg')))
    missing = [f for f in imgs if f not in rows]
    gone = [f for f in rows if f not in imgs and not os.path.exists(os.path.join(d, f))]
    for f in imgs:
        print('%-32s %s' % (f, ('%s p%s: %s' % rows[f]) if f in rows else 'NOT IN INDEX.md - say which figure it holds'))
    for f in gone:
        print('%-32s listed in INDEX.md but missing' % f)
    print('%d images, %d without an index row, %d rows for missing files' % (len(imgs), len(missing), len(gone)))
    return 1 if missing or gone else 0


def main():
    for tool in ('pdftotext', 'pdftoppm', 'pdfinfo'):
        if not shutil.which(tool):
            sys.exit('%s not found: install poppler (brew install poppler / apt install poppler-utils)' % tool)
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch'); f.add_argument('url'); f.add_argument('out')
    s = sub.add_parser('find'); s.add_argument('pdf'); s.add_argument('phrases', nargs='+'); s.add_argument('--context', type=int, default=0)
    g = sub.add_parser('page'); g.add_argument('pdf'); g.add_argument('n', type=int); g.add_argument('out'); g.add_argument('--dpi', type=int, default=170)
    g.add_argument('--label', help='what the page shows, recorded in INDEX.md next to the image')
    ix = sub.add_parser('index'); ix.add_argument('dir')
    a = ap.parse_args()
    if a.cmd == 'fetch':
        fetch(a.url, a.out)
    elif a.cmd == 'find':
        find(a.pdf, a.phrases, a.context)
    elif a.cmd == 'index':
        sys.exit(index(a.dir))
    else:
        page(a.pdf, a.n, a.out, a.dpi, a.label)


if __name__ == '__main__':
    main()
