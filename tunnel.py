import socket
from select import select
from time import strftime
from traceback import format_exc

LOCAL_HOST = '192.168.0.4'
REMOTE_HOST = '172.24.169.42'

LOCAL_PORT = 3000
REMOTE_PORT = 3000

def log(*args):
    print(strftime('[%Y-%m-%d %H:%M:%S]'), *args)

class Port():
    def __init__(self, local_address, remote_address):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(local_address)
        self.sock.listen()
        self.local_address = local_address
        self.remote_address = remote_address
        self.buffer = None

    def fileno(self):
        return self.sock.fileno()

    def accept(self):
        s1, _ = self.sock.accept()
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s2.connect(self.remote_address)
        except:
            try:
                s1.close()
            except:
                pass
            return ()

        local_sock = Tunnel(s1, 'local', self.local_address)
        remote_sock = Tunnel(s2, 'remote', self.remote_address)
        local_sock.peer = remote_sock
        remote_sock.peer = local_sock
        return (local_sock, remote_sock)

class Tunnel():
    def __init__(self, sock, half, addr):
        self.sock = sock
        self.half = half
        self.addr = '{}:{}'.format(*addr)
        self.buffer = b''
        self.sock.setblocking(0)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.done = False

    def fileno(self):
        return self.sock.fileno()

    def tunnel(self):
        try:
            packet = self.sock.recv(4096)
            if not packet:
                raise ConnectionResetError
        except (ConnectionResetError, ConnectionAbortedError):
            return self.peer.shutdown()

        self.peer.buffer += packet
        try:
            return self.peer.resend()
        except BlockingIOError:  # wait for select()
            return 0

    def resend(self):
        if not self.buffer:
            return 0

        try:
            sent = self.sock.send(self.buffer)
            if sent == 0:
                raise ConnectionResetError
        except (ConnectionResetError, ConnectionAbortedError):
            return self.peer.shutdown()

        self.buffer = self.buffer[sent:]
        return 0

    def shutdown(self):
        self.done = True
        errors = 0

        try:
            self.sock.shutdown(socket.SHUT_WR)
        except Exception:
            log(format_exc())
            errors += 1

        if self.peer.done:
            for s in (self.sock, self.peer.sock):
                try:
                    s.close()
                except Exception:
                    log(format_exc())
                    errors += 1

        return errors if errors else -1

socks = [Port((LOCAL_HOST, LOCAL_PORT), (REMOTE_HOST, REMOTE_PORT))]

log('Ready!')
while True:
    rlist, wlist, _ = select(socks, filter(lambda s: s.buffer, socks), (), 2)

    for s in wlist:
        try:
            result = s.resend()
        except Exception:
            log('Tunnel failed on', s.peer.sock, '\n' + format_exc())
            socks.remove(s)
            continue

        if result == -1:
            socks.remove(s)
            log('Connection shut down successfully ({}, {})'.format(s.addr, s.half))

        if result > 0:
            socks.remove(s)
            log('Connection shut down with', result, 'errors on', s.peer.sock,
                '({}, {})'.format(s.addr, s.half))

    for s in rlist:
        if s.buffer is None:
            list(map(socks.append, s.accept()))
            log('Tunnel opened to', s.remote_address)
            continue

        try:
            result = s.tunnel()
        except Exception:
            log('Tunnel failed on', s.sock, '\n' + format_exc())
            socks.remove(s)
            continue

        if result == -1:
            socks.remove(s)
            log('Connection shut down successfully ({}, {})'.format(s.addr, s.half))

        if result > 0:
            socks.remove(s)
            log('Connection shut down with', result, 'errors on', s.sock,
                '({}, {})'.format(s.addr, s.half))
