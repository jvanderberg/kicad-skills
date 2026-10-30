#!/usr/bin/env python3
"""Fetch a datasheet and find things in it, without grepping page by page.

  datasheet.py fetch URL OUT.pdf [--mpn MPN ...]    # refuses anything that is not a PDF (checks the %PDF magic)
  datasheet.py find DS.pdf "Layout Example" ["Figure 36" ...] [--context 1]
  datasheet.py page DS.pdf N OUT.png [--dpi 170] [--label "Figure 12-1 layout example"]
                                                    # render one page; --label records what it shows in INDEX.md
  datasheet.py index DIR                            # every image in a reference folder is named in its INDEX.md

fetch: manufacturer "symlink" URLs and distributor datasheet links can return an HTML page instead of the PDF - a
viewer page, a landing page, a login wall, or a "not found" page for a discontinued part (that itself is a lifecycle
warning: check the product page). The download is kept only if it starts with %PDF. A viewer page that embeds the
PDF (an iframe / embed / object source, a "pdfUrl" in the page's data, a link ending in .pdf) is followed: the links
are ranked (embedded viewers first, links naming the requested part's number next; certificates and other parts'
datasheets last) and the first that is a real PDF is saved, with the link it came from printed. Exit 1: not a PDF
(nothing saved, the candidate links tried are listed). Exit 2: the server refused a script (HTTP 401/403/429/503 or a
bot-protection page): nothing saved - open the URL in a browser (the user's, or browser automation), save the PDF as
OUT, or take it from the manufacturer's product page instead. A real PDF can still be the wrong document: LCSC's viewer
served an ISO certificate as the datasheet of two Sunlord inductors (C98350, C98361). So the saved PDF's text is
checked: with --mpn it must name the part (spaces and dashes ignored; a series prefix is reported as such), and a
document that reads like a certificate or test report rather than a datasheet is flagged. Exit 3: saved, but it failed
that check - open it, and find the real datasheet on the manufacturer's site if it is not one.
find: prints every page whose text contains each phrase (case-insensitive, whitespace-insensitive), with the matching
line, so you can name the page that holds a figure or section (e.g. "datasheet-p30.png = Figure 36, layout example")
in the project's reference notes. pdftotext's font warnings are suppressed.
page --label: appends (or updates) a row in INDEX.md next to the PNG - file, source PDF, page, what it shows - so a
reference folder says which file holds the figure (a folder with p28 and p29 and no note sent a later session to the
documentation-support page instead of the layout example). index: lists images with no INDEX.md row and rows whose
file is gone; exit 1 if either. Needs poppler (pdftotext, pdftoppm, pdfinfo).
"""
import argparse, os, re, shutil, subprocess, sys, urllib.error, urllib.parse, urllib.request


UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
      'Accept': 'application/pdf,text/html;q=0.9,*/*;q=0.8'}
BOT = re.compile(rb'cf-chl|challenge-platform|Just a moment|Attention Required|captcha|Access Denied|bot detection|'
                 rb'Request unsuccessful|Incapsula|perimeterx|akamai', re.I)


def get(url):
    """(data, HTTP status, content type, final url); network errors become status 0"""
    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.read(), r.status, r.headers.get('Content-Type', ''), r.geturl()
    except urllib.error.HTTPError as e:
        return e.read(), e.code, e.headers.get('Content-Type', ''), url
    except (urllib.error.URLError, OSError) as e:
        return str(e).encode(), 0, '', url


def blocked(data, status):
    """the reason a server refused a script, or None"""
    if status in (401, 403, 429, 503):
        m = BOT.search(data or b'')
        return 'HTTP %d%s' % (status, ', bot protection ("%s")' % m.group(0).decode('latin-1') if m else '')
    m = BOT.search(data[:20000] if data else b'')
    if m and not data.startswith(b'%PDF'):
        return 'bot-protection page ("%s")' % m.group(0).decode('latin-1')
    return None


def pdf_links(html, base, url):
    """candidate PDF links in a viewer / product page, best first"""
    t = html.decode('utf-8', 'replace').replace('\\/', '/').replace('\\u002F', '/')
    code = set(re.findall(r'C\d{4,}', url)) | set(re.findall(r'[A-Z0-9-]{6,}', os.path.basename(urllib.parse.urlparse(url).path).upper()))
    found = []
    for rank, rx in ((0, r'<(?:iframe|embed|object)[^>]+(?:src|data)=["\']([^"\']+)'),
                     (1, r'"(?:pdfUrl|pdf_url|datasheetUrl|fileUrl)"\s*:\s*"([^"]+)"'),
                     (2, r'(?:href|src)=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']'),
                     (3, r'(https?://[^"\'<>\s]+\.pdf(?:\?[^"\'<>\s]*)?)')):
        for m in re.finditer(rx, t, re.I):
            u = urllib.parse.urljoin(base, m.group(1).replace('&amp;', '&'))
            if not u.lower().startswith('http'):
                continue
            score = rank * 10
            if code and any(c in u.upper() for c in code):
                score -= 5
            if re.search(r'certif|rohs|reach|iso|/payment/', u, re.I):
                score += 50
            found.append((score, len(found), u))
    out = []
    for _, _, u in sorted(found):
        if u not in out and u != url:
            out.append(u)
    return out


CERT = re.compile(r'certificat|ISO\s*9001|ISO\s*14001|IATF\s*16949|test report|declaration of conformity', re.I)
SHEET = re.compile(r'electrical characteristics|absolute maximum|specification|dimension|ordering information|features', re.I)


def norm(s):
    return re.sub(r'[^A-Z0-9]', '', s.upper())


def content_problems(pdf, mpns=()):
    """(problems, note): does the saved PDF read like the datasheet of these part numbers?"""
    if not shutil.which('pdftotext'):
        return [], 'content not checked (pdftotext not found: install poppler)'
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True, errors='replace').stdout
    if not txt.strip():
        return [], 'content not checked: no text in the PDF (scanned?) - look at it'
    probs, notes, flat = [], [], norm(txt)
    for m in mpns:
        n = norm(m)
        if n in flat:
            continue
        pre = next((n[:k] for k in range(len(n) - 1, max(5, int(0.6 * len(n))) - 1, -1) if n[:k] in flat), None)
        if pre:
            notes.append('%s appears only as the series %s' % (m, pre))
        else:
            probs.append('it never mentions %s' % m)
    head = txt[:3000]
    if CERT.search(head) and not SHEET.search(txt):
        probs.append('it reads like a certificate or test report ("%s"), not a datasheet' % CERT.search(head).group(0))
    return probs, '; '.join(notes) or 'content checked: %s' % (', '.join(mpns) + ' named' if mpns else 'no certificate wording')


def fetch(url, out, max_follow=4, mpns=()):
    """save url as out only if it is (or the page it returns embeds) a real PDF. exit 1 not a PDF, 2 blocked"""
    data, status, ctype, final = get(url)
    why = blocked(data, status)
    if why:
        sys.stderr.write('blocked: %s for %s - nothing saved. The server refuses scripted downloads. Next step: open the URL '
                         'in a browser (the user\'s, or browser automation) and save the PDF as %s, or fetch it from the '
                         'manufacturer\'s product page instead.\n' % (why, url, out))
        sys.exit(2)
    tried = []
    if not data.startswith(b'%PDF') and status and data:
        for link in pdf_links(data, final, url)[:max_follow]:
            d2, s2, c2, _ = get(link)
            tried.append('%s (HTTP %s%s)' % (link, s2, ', PDF' if d2.startswith(b'%PDF') else ''))
            if d2.startswith(b'%PDF'):
                print('the page is a viewer: followed its PDF link %s' % link)
                data, status, ctype = d2, s2, c2
                break
            why = blocked(d2, s2)
            if why:
                sys.stderr.write('blocked: %s for the embedded PDF %s - nothing saved. Open it in a browser and save it as %s.\n' % (
                    why, link, out))
                sys.exit(2)
    if not data.startswith(b'%PDF'):
        title = re.search(rb'<title>(.*?)</title>', data, re.I | re.S)
        sys.stderr.write('not a PDF: HTTP %s, %s%s - nothing saved.%s Find the real PDF link on the product page.\n' % (
            status, ctype or 'no content type', ', page title "%s"' % title.group(1).decode('utf-8', 'replace').strip()[:80] if title else '',
            (' Links tried: ' + '; '.join(tried) + '.') if tried else ' No PDF link in the page.'))
        sys.exit(1)
    open(out, 'wb').write(data)
    print('saved %s (%d bytes)' % (out, len(data)))
    probs, note = content_problems(out, mpns)
    print(note)
    if probs:
        sys.stderr.write('WARNING: %s may not be the datasheet: %s. Open it; if it is not the datasheet, delete it and take '
                         'the PDF from the manufacturer\'s product page.\n' % (out, '; '.join(probs)))
        sys.exit(3)


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
        if not shutil.which(tool) and sys.argv[1:2] != ['fetch']:
            sys.exit('%s not found: install poppler (brew install poppler / apt install poppler-utils)' % tool)
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch'); f.add_argument('url'); f.add_argument('out')
    f.add_argument('--mpn', action='append', default=[], help='part number the datasheet must name (repeatable)')
    s = sub.add_parser('find'); s.add_argument('pdf'); s.add_argument('phrases', nargs='+'); s.add_argument('--context', type=int, default=0)
    g = sub.add_parser('page'); g.add_argument('pdf'); g.add_argument('n', type=int); g.add_argument('out'); g.add_argument('--dpi', type=int, default=170)
    g.add_argument('--label', help='what the page shows, recorded in INDEX.md next to the image')
    ix = sub.add_parser('index'); ix.add_argument('dir')
    a = ap.parse_args()
    if a.cmd == 'fetch':
        fetch(a.url, a.out, mpns=a.mpn)
    elif a.cmd == 'find':
        find(a.pdf, a.phrases, a.context)
    elif a.cmd == 'index':
        sys.exit(index(a.dir))
    else:
        page(a.pdf, a.n, a.out, a.dpi, a.label)


if __name__ == '__main__':
    main()
