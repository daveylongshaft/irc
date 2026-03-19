"""csc-ftpd: Distributed FTP daemon (drftpd-style).

Master node runs pyftpdlib FTP server + TLS listener for slaves.
Slave nodes connect to master, report file inventory, handle data transfers.
FTP clients connect to master which routes transfers to/from slaves.
"""
