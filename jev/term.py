"""A pty-backed 80x24 terminal, emulated with pyte. Same code drives local NetHack and SSH."""
try:
    import pty
except Exception:
    pty = None
try:
    import pyte
except Exception:
    pyte = None
import os, select, signal, time

COLS, LINES = 80, 24

class Term:
    def __init__(self, argv, env=None, idle=0.04, floor=0.0):
        self.gap, self.last = 0.0, 0.0
        self.idle = idle
        self.screen = pyte.Screen(COLS, LINES)
        self.stream = pyte.ByteStream(self.screen)
        self._closed = False
        self.alive = True
        env = dict(os.environ, **(env or {}), TERM='xterm-256color', LINES=str(LINES), COLUMNS=str(COLS))
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe(argv[0], argv, env)
        import fcntl, struct, termios
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', LINES, COLS, 0, 0))
