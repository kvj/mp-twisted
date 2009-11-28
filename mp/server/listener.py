import logging
import socket
import os
from twisted.internet.protocol import Factory
from twisted.internet import reactor
from mp.server import connection
from mp import common
from mp.server import manager
from mp.server import daemon

class MyDaemon(daemon.Daemon):
	def run(self):
		logging.info('Starting server as daemon')
		run_server()
		
def run_server():
	manager.init_plugins()
	try:
		f = Factory()
		f.protocol = connection.ServerConnection
		if not hasattr(socket, 'AF_UNIX') or common.config.getboolean('Server', 'force_tcp'):
			logging.info('Open tcp port')
			reactor.listenTCP(common.config.getint('Server', 'port'), f)
		else:
			logging.info('Open file socket')
			file_socket = common.config.get('Server', 'file')
			try:
				os.remove(file_socket)
			except:
				pass
			reactor.listenUNIX(file_socket, f)
		logging.info("Server started")
		reactor.run()
	except Exception, err:
		logging.critical("Can't start server: %s", err)
	
	

def start_server():
	common.init_server()
	#Daemonise, if necessary
	#Check client settings
	if common.config.has_option('Client', 'auto_server') and common.config.getboolean('Client', 'auto_server'):
		#Demonise
		common.daemon = MyDaemon('/tmp/mp.pid')
		common.daemon.start()
	else:
		run_server()
	