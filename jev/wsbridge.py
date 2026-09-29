"""Relay a pty (stdin/stdout) to Hardfought's web terminal websocket, so Term can drive it like ssh.

    python -m jev.wsbridge [wss://www.hardfought.org/ws-hterm]

SSH (port 22) is unreachable from some networks; the browser terminal speaks raw tty bytes over wss://.
"""
import os, select, sys, tty
import websocket

URL = sys.argv[1] if len(sys.argv) > 1 else 'wss://www.hardfought.org/ws-hterm'


def main():
    ws = websocket.create_connection(f'{URL}?c=80&l=24', timeout=15, header=['Origin: https://www.hardfought.org'])
    if os.isatty(0):
        tty.setraw(0)
    while True:
        r, _, _ = select.select([0, ws.sock], [], [], 30)
        if not r:
            ws.ping()
            continue
        if 0 in r:
            data = os.read(0, 4096)
            if not data:
                break
            ws.send_binary(data)
        # drain: TLS may hold further frames already read off the socket, which select() cannot see
        while ws.sock in r or ws.sock.pending():
            r = ()
            op, data = ws.recv_data()
            if op == websocket.ABNF.OPCODE_CLOSE:
                return ws.close()
            if op == websocket.ABNF.OPCODE_BINARY:
                os.write(1, data)
    ws.close()


if __name__ == '__main__':
    main()
