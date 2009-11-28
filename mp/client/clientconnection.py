#!/usr/bin/env python

from mp import common, message
from twisted.internet import reactor
from twisted.internet.protocol import ClientFactory
from twisted.words.xish.xmlstream import XmlStream
import logging
import socket
import subprocess
import time
import os

class ClientConnection(XmlStream):

	def __init__(self, handler):
		self.handler = handler
		self.id = 0
		XmlStream.__init__(self)

	def connectionMade(self):
		#logging.debug('connectionMade')
		XmlStream.connectionMade(self)
		#Send start stream
		XmlStream.send(self, '<?xml version="1.0" encoding="utf-8"?><root>')

	def connectionLost(self, reason):
		#logging.debug('connectionLost')
		XmlStream.connectionLost(self, reason)
		self.handler.client_disconnected(self)

	def send_message(self, m):
		logging.debug('Sending %s', m.to_xml())
		XmlStream.send(self, m.to_xml())

	def onDocumentStart(self, rootElement):
		XmlStream.onDocumentStart(self, rootElement)
		#logging.debug('onDocumentStart')
		#m = message.Message('msg')
		#m.set('from', 'me')
		#self.send_message(m)
		self.handler.client_connected(self)


	def onElement(self, element):
		XmlStream.onElement(self, element)
		#logging.debug('Received message %s', element.toXml())
		m = message.Message(message = element)
		#Pass to client handler
		try:
			self.handler.process_message(m, self)
		except Exception, err:
			logging.exception('Error processing incoming message: %s', err)

class ConnectionFactory(ClientFactory):

	def __init__(self, listener, reconnect = False):
		self.listener = listener
		self.reconnect = reconnect

	def startedConnecting(self, connector):
		pass

	def buildProtocol(self, addr):
		#logging.info('Connection with server established!')
		return ClientConnection(self.listener)

	def clientConnectionLost(self, connector, reason):
		ClientFactory.clientConnectionLost(self, connector, reason)

	def clientConnectionFailed(self, connector, reason):
		logging.info('Connection failed')
		ClientFactory.clientConnectionFailed(self, connector, reason)
		#If first connection was failed - try to start server
		if not self.reconnect:
			#Start, reconnect
			try:
				subprocess.Popen(['python', 'server.py']).wait()
			except Exception, err:
				logging.exception('Error starting server: %s', err)
			time.sleep(3)
			do_connect(self.listener, True)
		else:
			#Stop reactor, exit
			logging.info('Can\'t connect to server, exiting')
			reactor.stop()


def process_message(message, connection):
	pass

def do_connect(listener, reconnect = False):
	if not hasattr(socket, 'AF_UNIX') or common.config.getboolean('Client', 'force_tcp'):
		logging.info('Open tcp port')
		reactor.connectTCP('localhost', common.config.getint('Server', 'port'), ConnectionFactory(listener, reconnect))
	else:
		logging.info('Open file socket')
		reactor.connectUNIX(common.config.get('Server', 'file'), ConnectionFactory(listener, reconnect))
	logging.info("Client started")

def start_client(listener):
	common.init_client()
	auto_server = False
	if common.config.has_option('Client', 'auto_server') and common.config.getboolean('Client', 'auto_server'):
		auto_server = True
	do_connect(listener, not auto_server)
	reactor.run()
