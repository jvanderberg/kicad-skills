"""datasheet.py fetch against a local HTTP server (no network):   python3 -m pytest -q tests
A distributor datasheet link that returns an HTML viewer is followed to the PDF it embeds (and not to a certificate or
another part's datasheet on the same page); a bot-protection 403 is reported as blocked (exit 2) with the next step;
a page with no PDF anywhere saves nothing (exit 1)."""
import http.server, os, subprocess, sys, threading
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = b'%PDF-1.4\n% synthetic\n'
PAGES = {
    '/datasheet/C1234.pdf': (200, 'text/html', b'<html><title>viewer</title><a href="/cert/rohs-C1234.pdf">RoHS</a>'
                                              b'<script>{"pdfUrl":"https:\\/\\/OTHER\\/x.pdf"}</script>'
                                              b'<iframe src="/files/abc.pdf?productCode=C1234"></iframe>'
                                              b'<a href="/files/other.pdf?productCode=C9999">alt</a></html>'),
    '/files/abc.pdf': (200, 'application/pdf', PDF),
    '/cert/rohs-C1234.pdf': (200, 'application/pdf', b'%PDF-1.4 certificate'),
    '/blocked.pdf': (403, 'text/html', b'<html><title>Just a moment...</title><div id="cf-chl-widget"></div></html>'),
    '/nolink.pdf': (200, 'text/html', b'<html><title>Product not found</title></html>'),
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


def fetch(server, path, out):
    url = 'http://127.0.0.1:%d%s' % (server.server_port, path)
    return subprocess.run([sys.executable, os.path.join(HERE, 'datasheet.py'), 'fetch', url, out], capture_output=True, text=True)


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
