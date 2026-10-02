"""Entry point: runs the bot in a thread and serves the dashboard + API on 127.0.0.1.

    python -m jev.server              # local NetHack build in ./nethack
    python -m jev.server --hardfought # SSH to hardfought.org (see jev/hardfought.py)
"""
import argparse, json, os, threading, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from .bot import Bot, ROOT, runs_home
from .jevapi import Jev
from .term import Term


def load_env():
    try:
        for line in open(os.path.join(ROOT, '.env')):
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ.setdefault(k, v.strip().strip('"\''))
    except OSError:
        pass


def local_launcher(name):
    def launch():
        return Term([os.path.join(ROOT, 'nethack/bin/nethack'), '-u', name],
                    {'NETHACKOPTIONS': '@' + os.path.join(ROOT, 'jev/nethackrc')}, idle=0.015)  # a local pty flushes a whole frame at once
    return launch


def make_handler(bot):
    dist = os.path.join(ROOT, 'web', 'dist')

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=dist, **kw)

        def log_message(self, *a):
            pass

        def send_json(self, obj, code=200):
            body = json.dumps(obj, default=list).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/api/state':
                return self.send_json(bot.state())
            if self.path == '/api/events':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                seen = -1
                try:
                    while True:
                        if bot.version != seen:
                            seen = bot.version
                            self.wfile.write(b'data: ' + json.dumps(bot.state(), default=list).encode() + b'\n\n')
                            self.wfile.flush()
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    return
            if self.path.split('?')[0] == '/':
                self.path = '/index.html'
            return super().do_GET()

        def do_POST(self):
            if self.path != '/api/control':
                return self.send_json({'ok': False}, 404)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            except ValueError:
                return self.send_json({'ok': False, 'error': 'bad json'}, 400)
            a = body.get('action')
            if a == 'pause':
                bot.paused = True
            elif a == 'resume':
                bot.paused = False
            elif a == 'step':
                bot.step_once = True
            elif a == 'order':
                bot.order = str(body.get('text', ''))[:1000]
                bot.log(f'standing order: {bot.order}')
            elif a == 'speed':
                bot.delay_ms = max(0, min(2000, int(body.get('delay_ms', 250))))
            elif a == 'new_game' and bot.t:
                bot.log('operator requested a new game', 'warn')
                bot.fresh = True
                bot.t.close()
            else:
                return self.send_json({'ok': False, 'error': 'unknown action'}, 400)
            bot.touch()
            return self.send_json({'ok': True})

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hardfought', action='store_true')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8770)))
    ap.add_argument('--name', default='Jev')
    ap.add_argument('--paused', action='store_true')
    args = ap.parse_args()
    load_env()
    from .jevapi import is_local  # a local endpoint keeps its own ledger so hosted spend stays exact
    jev = Jev(os.environ.get('JEV_API_KEY', ''), float(os.environ.get('JEV_BUDGET_USD', 5)), os.path.join(runs_home(args.name), 'budget-local.json') if is_local() else os.path.join(ROOT, 'runs', 'budget.json'))  # hosted spend is one budget across instances
    if args.hardfought:
        from .hardfought import launcher
        bot = Bot(launcher(os.environ['HARDFOUGHT_USERNAME'], os.environ['HARDFOUGHT_PASSWORD']), jev, 'hardfought')
    else:
        bot = Bot(local_launcher(args.name), jev, 'local', args.name)
    bot.paused = args.paused
    threading.Thread(target=bot.play, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(bot))
    print(f'dashboard: http://{args.host}:{args.port}', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
