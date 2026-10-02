"""Minimal TypeSafe Jev client (stdlib only) with a persistent spend cap."""
import http.client, json, os, socket, ssl, threading, time, urllib.parse


# JEV_ENDPOINT points the bot at any server speaking the same /v1/systemone protocol (a local Jev clone);
# plain http:// is fine for localhost. JEV_MODEL overrides the model name sent.
HOSTED = 'https://api.typesafe.ai/v1/systemone'
is_local = lambda: not os.environ.get('JEV_ENDPOINT', HOSTED).startswith('https://api.typesafe.ai')  # read late: server.py loads .env after imports
USD_PER_INPUT_TOKEN = 0.042e-6  # published launch price; responses carry no cost field


class FastConnect(http.client.HTTPSConnection):
    """Try every resolved address with a short connect timeout. Some edge IPs are intermittently
    unreachable from here; curl hides that with happy-eyeballs, urllib waits out the full timeout."""

    addrs = {}

    def resolve(self):
        """getaddrinfo sometimes hangs for ~20s here, so bound it and fall back to the last good answer."""
        out = []
        t = threading.Thread(target=lambda: out.append(socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)), daemon=True)
        t.start()
        t.join(2)
        if out:
            FastConnect.addrs[self.host] = out[0]
        return FastConnect.addrs.get(self.host) or []

    def connect(self):
        err = None
        for fam, typ, proto, _, addr in self.resolve():
            s = socket.socket(fam, typ, proto)
            s.settimeout(2)
            try:
                s.connect(addr)
            except OSError as e:
                s.close()
                err = e
                continue
            s.settimeout(self.timeout)
            self.sock = self._context.wrap_socket(s, server_hostname=self.host)
            return
        raise err or OSError('no addresses')


class Jev:
    def __init__(self, key, budget_usd=5.0, ledger='runs/budget.json'):
        self.key, self.budget, self.ledger = key, budget_usd, ledger
        self.endpoint, self.model, self.local = os.environ.get('JEV_ENDPOINT', HOSTED), os.environ.get('JEV_MODEL', 'jev-latest'), is_local()
        if 'lunaroute.com' in self.endpoint:  # gateway serving djev etc.; its pricing isn't known, so no budget is tracked
            self.key = os.environ.get('LUNAROUTE_API_KEY')
        self.stats = dict(calls=0, errors=0, cost_usd=0.0, latency_total_ms=0.0, last_model=None)
        try:
            self.stats.update(json.load(open(ledger)))
        except (OSError, ValueError):
            pass

    def ask(self, state, questions, timeout=None):
        """Returns (answers, meta). Raises on transport/validation failure."""
        if self.stats['cost_usd'] >= self.budget and not self.local:
            raise RuntimeError(f'Jev budget ${self.budget} exhausted (see {self.ledger})')
        timeout = timeout or (120 if self.local else 8)  # a local model's first call loads weights; Gemma on MPS is slow
        req = dict(state=state, model=self.model, questions=questions)
        body = json.dumps(req).encode()
        url = urllib.parse.urlsplit(self.endpoint)
        t0 = time.time()
        for attempt in range(4):
            try:
                if not getattr(self, 'conn', None):  # keep-alive: skip the TCP+TLS handshake on every call
                    self.conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=timeout) if url.scheme == 'http' else \
                        FastConnect(url.hostname, url.port or 443, timeout=timeout, context=ssl.create_default_context())
                try:
                    self.conn.request('POST', url.path, body, {'Authorization': 'Bearer ' + (self.key or 'local'), 'Content-Type': 'application/json'})
                    r = self.conn.getresponse()
                    raw = r.read()
                except BaseException:
                    self.conn.close()
                    self.conn = None
                    raise
                if r.will_close:
                    self.conn.close()
                    self.conn = None
                if r.status >= 400:
                    if r.status < 500 and r.status != 429:
                        raise RuntimeError(f'Jev HTTP {r.status}: {raw[:300]!r}')
                    raise OSError(f'HTTP {r.status}')
                resp = json.loads(raw)
                self.last = dict(request=req, response=resp)  # shown in the dashboard's request tab
                break
            except (OSError, ValueError, http.client.HTTPException) as e:
                self.stats['errors'] += 1
                err = e
                time.sleep(0.5 + attempt)
        else:
            raise RuntimeError(f'Jev unreachable: {err}')
        ms = (time.time() - t0) * 1000
        answers = resp.get('answers') or {}
        for k, q in questions.items():
            a = answers.get(k)
            if not a or (q['type'] == 'choice' and a.get('choice') not in q['criteria']):
                self.stats['errors'] += 1
                raise RuntimeError(f'Jev answer invalid for {k}: {a}')
        tokens = (resp.get('usage') or {}).get('input_tokens') or len(body) / 4
        s = self.stats
        s['calls'] += 1
        s['cost_usd'] += 0 if self.local else tokens * USD_PER_INPUT_TOKEN
        s['latency_total_ms'] += ms
        s['last_model'] = os.environ.get('JEV_LABEL') or resp.get('model')  # Kev just echoes the requested 'jev-latest'
        os.makedirs(os.path.dirname(self.ledger), exist_ok=True)
        json.dump(s, open(self.ledger, 'w'))
        return answers, dict(latency_ms=round(ms), model=s['last_model'], input_tokens=tokens)

    def summary(self):
        s = self.stats
        return dict(calls=s['calls'], errors=s['errors'], cost_usd=round(s['cost_usd'], 6), budget_usd=self.budget,
                    avg_latency_ms=round(s['latency_total_ms'] / s['calls']) if s['calls'] else 0, last_model=s['last_model'],
                    last=getattr(self, 'last', None))
