"""datasheet.py fetch against a local HTTP server (no network):   python3 -m pytest -q tests
A distributor datasheet link that returns an HTML viewer is followed to the PDF it embeds (and not to a certificate or
another part's datasheet on the same page); a bot-protection 403 is reported as blocked (exit 2) with the next step;
a page with no PDF anywhere saves nothing (exit 1)."""
import http.server, os, shutil, subprocess, sys, threading
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = b'%PDF-1.4\n% synthetic\n'


def text_pdf(*lines):
    """a minimal one-page PDF whose text pdftotext can read"""
    body = 'BT /F1 11 Tf 72 720 Td 14 TL ' + ' '.join('(%s) Tj T*' % l for l in lines) + ' ET'
    objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
            '<< /Length %d >>\nstream\n%s\nendstream' % (len(body), body), '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offs = '%PDF-1.4\n', []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += '%d 0 obj\n%s\nendobj\n' % (i, o)
    x = len(out)
    out += 'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1) + ''.join('%010d 00000 n \n' % o for o in offs)
    return (out + 'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, x)).encode()


CERT_PDF = text_pdf('CERTIFICATE', 'Shenzhen Sunlord Electronics Co., Ltd.', 'ISO 9001:2015 Quality Management System')
SHEET_PDF = text_pdf('SWPA Series SMD Power Inductor', 'Features: low DCR', 'Ordering information: SWPA4030S100MT',
                     'Electrical characteristics')
PAGES = {
    '/datasheet/C1234.pdf': (200, 'text/html', b'<html><title>viewer</title><a href="/cert/rohs-C1234.pdf">RoHS</a>'
                                              b'<script>{"pdfUrl":"https:\\/\\/OTHER\\/x.pdf"}</script>'
                                              b'<iframe src="/files/abc.pdf?productCode=C1234"></iframe>'
                                              b'<a href="/files/other.pdf?productCode=C9999">alt</a></html>'),
    '/files/abc.pdf': (200, 'application/pdf', PDF),
    '/cert/rohs-C1234.pdf': (200, 'application/pdf', b'%PDF-1.4 certificate'),
    '/blocked.pdf': (403, 'text/html', b'<html><title>Just a moment...</title><div id="cf-chl-widget"></div></html>'),
    '/nolink.pdf': (200, 'text/html', b'<html><title>Product not found</title></html>'),
    '/cert.pdf': (200, 'application/pdf', CERT_PDF),
    '/sheet.pdf': (200, 'application/pdf', SHEET_PDF),
}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        st, ct, body = PAGES.get(self.path.split('?')[0], (404, 'text/html', b'<title>404</title>'))
        self.send_response(st); self.send_header('Content-Type', ct); self.end_headers(); self.wfile.write(body)
        self.server.log.append(self.path)

    def log_message(self, *a):
        pass


@pytest.fixture(scope='module')
def server():
    s = http.server.HTTPServer(('127.0.0.1', 0), H); s.log = []
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()


def fetch(server, path, out, *args):
    url = 'http://127.0.0.1:%d%s' % (server.server_port, path)
    return subprocess.run([sys.executable, os.path.join(HERE, 'datasheet.py'), 'fetch', url, out, *args], capture_output=True, text=True)


def test_viewer_page_followed_to_its_pdf(server, tmp_path):
    out = str(tmp_path / 'ds.pdf')
    r = fetch(server, '/datasheet/C1234.pdf', out)
    assert r.returncode == 0, r.stderr
    assert open(out, 'rb').read() == PDF and 'followed its PDF link' in r.stdout and '/files/abc.pdf' in r.stdout, r.stdout
    assert not any('rohs' in p for p in server.log), server.log           # certificates are ranked last


def test_bot_protection_is_blocked_not_html(server, tmp_path):
    out = str(tmp_path / 'b.pdf')
    r = fetch(server, '/blocked.pdf', out)
    assert r.returncode == 2 and 'blocked: HTTP 403, bot protection' in r.stderr and 'browser' in r.stderr, r.stderr
    assert not os.path.exists(out)


def test_page_without_pdf_saves_nothing(server, tmp_path):
    out = str(tmp_path / 'n.pdf')
    r = fetch(server, '/nolink.pdf', out)
    assert r.returncode == 1 and 'not a PDF' in r.stderr and 'Product not found' in r.stderr, r.stderr
    assert not os.path.exists(out)


@pytest.mark.skipif(not shutil.which('pdftotext'), reason='needs poppler (pdftotext)')
def test_pdf_that_is_not_the_datasheet_is_flagged(server, tmp_path):
    """LCSC's viewer served an ISO certificate as two inductors' datasheet: saved, but exit 3 with a WARNING"""
    out = str(tmp_path / 'SWPA4030S100MT.pdf')
    r = fetch(server, '/cert.pdf', out, '--mpn', 'SWPA4030S100MT')
    assert r.returncode == 3 and os.path.exists(out), r.stdout + r.stderr
    assert 'never mentions SWPA4030S100MT' in r.stderr and 'certificate' in r.stderr, r.stderr
    r = fetch(server, '/cert.pdf', out)                                   # no --mpn: the wording alone is enough
    assert r.returncode == 3 and 'reads like a certificate' in r.stderr, r.stderr
    r = fetch(server, '/sheet.pdf', out, '--mpn', 'SWPA4030S100MT')
    assert r.returncode == 0 and 'SWPA4030S100MT named' in r.stdout, r.stdout + r.stderr
    r = fetch(server, '/sheet.pdf', out, '--mpn', 'SWPA4030S220MT')       # another value of the series
    assert r.returncode == 0 and 'only as the series SWPA4030S' in r.stdout, r.stdout + r.stderr
