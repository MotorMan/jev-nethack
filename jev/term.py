"""A pty-backed 80x24 terminal, emulated with pyte. Same code drives local NetHack and SSH."""
import os, pty, select, signal, time
import pyte

COLS, LINES = 80, 24


class Term:
    def __init__(self, argv, env=None, idle=0.04, floor=0.0):
        self.gap, self.last = 0.0, 0.0  # minimum seconds between sends (the UI delay); thinking time counts toward it
        self.floor = floor  # hard minimum gap that the UI delay cannot lower: public servers (HF, NAO) need it, local play is 0 (unlimited)
        self.idle = idle  # seconds of silence that mean "the game is waiting for input"
        self.screen = pyte.Screen(COLS, LINES)
        self.stream = pyte.ByteStream(self.screen)
        env = dict(os.environ, **(env or {}), TERM='xterm-256color', LINES=str(LINES), COLUMNS=str(COLS))
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe(argv[0], argv, env)
        import fcntl, struct, termios
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', LINES, COLS, 0, 0))
        self.alive = True

    def pump(self, timeout=5.0):
        """Read until output has been quiet for `idle` seconds (or timeout). Returns bytes read."""
        end, last, n = time.time() + timeout, time.time(), 0
        while self.alive and time.time() < end:
            r, _, _ = select.select([self.fd], [], [], self.idle)
            if r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    data = b''
                if not data:
                    self.alive = False
                    break
                self.stream.feed(data)
                n += len(data)
                last = time.time()
            elif n or time.time() - last > self.idle * 4:
                break
        return n

    def send(self, keys, timeout=5.0):
        if isinstance(keys, str):
            keys = keys.encode()
        if not self.alive:
            return 0
        time.sleep(max(0.0, self.last + max(self.gap, self.floor) - time.time()))
        self.last = time.time()
        try:
            os.write(self.fd, keys)
        except OSError:
            self.alive = False
            return 0
        return self.pump(timeout)

    def lines(self):
        return self.screen.display

    def cursor(self):
        return self.screen.cursor.x, self.screen.cursor.y

    def cell(self, x, y):
        return self.screen.buffer[y][x]

    def runs(self):
        """Screen as rows of [text, fg, bg, bold, reverse] runs, for the UI."""
        out = []
        for y in range(LINES):
            row, cur = [], None
            line = self.screen.buffer[y]
            for x in range(COLS):
                c = line[x]
                key = (c.fg, c.bg, c.bold, c.reverse)
                if cur and cur[1:] == list(key):
                    cur[0] += c.data
                else:
                    cur = [c.data, *key]
                    row.append(cur)
            out.append(row)
        return out

    def close(self):
        """SIGHUP (NetHack saves on hangup), then SIGKILL if it lingers."""
        for sig in (signal.SIGHUP, signal.SIGKILL):
            try:
                os.kill(self.pid, sig)
            except OSError:
                break
            for _ in range(30):
                try:
                    if os.waitpid(self.pid, os.WNOHANG)[0]:
                        break
                except ChildProcessError:  # already reaped by another thread's close()
                    break
                time.sleep(0.1)
            else:
                continue
            self.alive = False
            return
        self.alive = False
