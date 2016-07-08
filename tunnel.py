import socket
from traceback import format_exc
from time import sleep, time
from sys import argv
from os import spawnl, P_NOWAIT
from threading import Thread

HOST = '192.168.32.48'
LOGIN_PORT = 11093

IN, OUT = 0, 1

zones = {
    'running': [],
    'waiting': [],
}

def start_zone(port):
    zones['waiting'].append(
        Thread(target=zone_serve,
               name='{}'.format(port),
               args=(port,)))

def zone_serve(port):
    def log(*args):
        print('[{}]'.format(port), *args)

    sock = [None, None]

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', port))
    server.listen(1)

    log('awaiting connection in port {}'.format(port))
    sock[IN] = server.accept()[0]
    sock[IN].setblocking(0)
    log('client has connected')

    sock[OUT] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #sock[OUT].setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock[OUT].connect((HOST, port))
    sock[OUT].setblocking(0)
    log('connection has been tunnelled')

    try:
        while True:
            try:
                packet = sock[OUT].recv(65535)
                if packet:
                    sock[IN].send(packet)
                else:
                    log('server closed the connection')
                    break
            except ConnectionResetError:
                log('server closed the connection')
                break
            except BlockingIOError:
                pass
            except KeyboardInterrupt:
                break
            except:
                log(time())
                log(format_exc())
                break

            try:
                packet = sock[IN].recv(65535)
                if packet:
                    sock[OUT].send(packet)
                else:
                    log('client closed the connection')
                    break
            except ConnectionResetError:
                log('client closed the connection')
                break
            except BlockingIOError:
                pass
            except KeyboardInterrupt:
                break
            except:
                log(time())
                log(format_exc())
                break

    finally:
        errors = 0

        try:
            sock[IN].close()
        except:
            errors += 1

        try:
            sock[OUT].close()
        except:
            errors += 1

        try:
            server.close()
        except:
            errors += 1

        log('tunnel torn down with {} errors'.format(errors))


#############


start_zone(LOGIN_PORT)
for port in range(11601, 11743):
    if port == 11707:
        port = 11107
    start_zone(port)

try:
    while True:
        for i, zone in enumerate(zones['running']):
            if not zone.is_alive():
                zones['running'].pop(i)
                zone.join()
                print('reaped zone {}'.format(zone.name))
                start_zone(int(zone.name))

        if zones['waiting']:
            zone = zones['waiting'].pop(0)
            zone.start()
            zones['running'].append(zone)

        sleep(0.5)

finally:
    errors = 0
    while zones['running']:
        zone = zones['running'].pop(0)

        try:
            zone.join()
            print('reaped zone {}'.format(zone.name))
        except:
            errors += 1

    print('exited with {} thread.join exceptions'.format(errors))
