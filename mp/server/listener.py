import logging
import socket
from twisted.internet.protocol import Factory
from twisted.internet import reactor
from mp.server import connection
from mp import common
from mp.server import manager

def start_server():
	common.init_server()
	manager.init_plugins()
	try:
		f = Factory()
		f.protocol = connection.ServerConnection
		if not hasattr(socket, 'AF_UNIX') or common.config.getboolean('Server', 'force_tcp'):
			logging.info('Open tcp port')
			reactor.listenTCP(common.config.getint('Server', 'port'), f)
		else:
			logging.info('Open file socket')
			reactor.listenUNIX(common.config.get('Server', 'file'), f)
		logging.info("Server started")
		reactor.run()
	except Exception, err:
		logging.critical("Can't start server: %s", err)
