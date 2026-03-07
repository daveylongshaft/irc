import socket
import time
import random
import threading
import queue
from csc_service.shared.version import Version


class Network( Version ):
    def __init__(self, host="127.0.0.1", port=9525, name="network"):
        """
        Initializes the Network class.

        - What it does: Sets up the UDP socket, message queue, and keepalive mechanism.
        - Arguments:
            - `host` (str): The host address to bind to.
            - `port` (int): The port to listen on.
            - `name` (str): The name of the network instance.
        - What calls it: Called by the `__init__` method of its direct subclass, `Service`.
        - What it calls: `super().__init__()`, `socket.socket()`, `queue.Queue()`, `time.time()`, `random.randint()`, `print()`.
        """
        super().__init__()
        self.server_addr = (host, port)
        self.sock = socket.socket( socket.AF_INET, socket.SOCK_DGRAM )
        self.sock.settimeout( 1.0 )
        self.name = name
        self.message_queue = queue.Queue()
        self._listener_thread = None
        self._running = True
        self.buffsize = 65500
        self.last_keepalive = time.time()
        self.clients = {}
        self.keepalive_interval = random.randint( 60, 120 )
        #print(f"{self.name}->",end=None)
        self.log( f"[Network] Initialized for {self.server_addr} (keepalive every {self.keepalive_interval}s)" )

    def _network_listener(self):
        """
        Listens for all incoming data and filters keepalives.

        - What it does: Runs in a separate thread, continuously listening for
          incoming UDP packets. It filters out keepalive messages and puts all
          other data into the `message_queue`.
        - Arguments: None.
        - What calls it: Started by `start_listener()`.
        - What it calls: `self.log()`, `self.sock.recvfrom()`, `time.time()`,
          `bytes.decode()`, `str.strip()`, `str.upper()`, `self.message_queue.put()`.
        """
        self.log( "[Network] Listener thread started." )
        while self._running:
            try:
                data, addr = self.sock.recvfrom( self.buffsize )
                self.clients[addr] = {"last_seen": time.time()}

#                self.clients[addr] = time.time()

                # --- FIX: Put raw bytes into the queue ---
                # Decode a temporary copy ONLY to check for keepalives.
                text_for_check = data.decode( "utf-8", errors="ignore" ).strip()
                if text_for_check.upper() in ["<KEEPALIVE>", "NOOP"] or text_for_check.upper().startswith("PONG"):
                    continue  # Discard and do not add to the queue.

                # If it's not a keepalive, put the ORIGINAL, UNMODIFIED `data` (bytes) into the queue.
                self.message_queue.put( (data, addr) )

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.log( f"[Network] Listener thread error: {e}" )
                    time.sleep( 1 )
        self.log( "[Network] Listener thread stopped." )

    def start_listener(self):
        """
        Starts the background network listener thread.

        - What it does: Creates and starts the `_network_listener` thread.
        - Arguments: None.
        - What calls it: Called by `Server.__init__()`.
        - What it calls: `threading.Thread()`, `thread.start()`, `self.log()`.
        """
        if self._listener_thread is None:
            self._running = True
            self._listener_thread = threading.Thread( target=self._network_listener, daemon=True )
            self._listener_thread.start()
            self.log( f"Listener status: {self._listener_thread.is_alive()}" )

    def get_message(self):
        """
        Gets one message tuple (bytes, addr) from the buffer.

        - What it does: Retrieves a message from the front of the `message_queue`.
        - Arguments: None.
        - What calls it: Called by `Server._network_loop()`.
        - What it calls: `self.message_queue.get_nowait()`.
        - Returns:
            - A tuple `(bytes, addr)` or `None` if the queue is empty.
        """
        try:
            return self.message_queue.get_nowait()
        except queue.Empty:
            return None

    def send(self, message):
        """
        Send a message to the server, encoding if necessary.

        - What it does: A convenience method that sends a message to the configured
          `server_addr`.
        - Arguments:
            - `message` (str or bytes): The message to send.
        - What calls it: Called by `maybe_send_keepalive()`.
        - What it calls: `self.sock_send()`, `self.log()`.
        """
        try:
            # sock_send now handles both types, so we just pass it on.
            self.sock_send( message, self.server_addr )
        except Exception as e:
            self.log( f"[send] Error sending data: {e}" )

    def sock_send(self, data, addr):
        """
        Sends data in chunks, handling both string and bytes types safely.

        - What it does: Encodes string data to bytes, splits the data into
          chunks smaller than the buffer size, and sends each chunk.
        - Arguments:
            - `data` (str or bytes): The data to send.
            - `addr` (tuple): The `(host, port)` address to send to.
        - What calls it: Called by `send()` and by `Server.broadcast()`.
        - What it calls: `isinstance()`, `str.encode()`, `self.sock.sendto()`, `time.sleep()`, `self.log()`.
        """
        try:
            message_bytes = data if isinstance( data, bytes ) else str( data ).encode( "utf-8" )

            # This is the correct way to chunk the data.
            pieces = [message_bytes[i:i + self.buffsize] for i in range( 0, len( message_bytes ), self.buffsize )]

            for i, piece in enumerate( pieces ):
                self.sock.sendto( piece, addr )
                time.sleep( 0.01 )
        except Exception as e:
            self.log( f"Send failed to {addr}: {e}" )

    def maybe_send_keepalive(self):
        """
        Sends a periodic keep-alive packet silently.

        - What it does: Checks if the keepalive interval has passed and, if so,
          sends a keepalive message and resets the timer.
        - Arguments: None.
        - What calls it: Called by the `Client`'s main loop.
        - What it calls: `time.time()`, `self.send()`, `random.randint()`.
        """
        now = time.time()
        if now - self.last_keepalive >= self.keepalive_interval:
            self.send( "PING :keepalive\r\n" )
            self.last_keepalive = now
            self.keepalive_interval = random.randint( 60, 120 )

    def close(self):
        """
        Cleanly close the network socket and stop the listener thread.

        - What it does: Signals the listener thread to stop, waits for it to
          join, and then closes the UDP socket.
        - Arguments: None.
        - What calls it: Called by `Server.run()` during shutdown.
        - What it calls: `thread.join()`, `self.sock.close()`, `self.log()`.
        """
        self._running = False
        if self._listener_thread is not None:
            self._listener_thread.join( timeout=1.5 )
        try:
            self.sock.close()
            self.log( "[Network] Socket closed." )
        except Exception as e:
            self.log( f"[Network] Error closing socket: {e}" )

    def connected_for(self):
        """
        A placeholder method for subclasses to override.
        """
        return 0.0


if __name__ == '__main__':
    network = Network()
    network.run()
