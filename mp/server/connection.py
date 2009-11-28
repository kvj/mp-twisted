#!/usr/bin/env python

from twisted.words.xish.xmlstream import XmlStream
import logging
from mp.server import manager
from mp import message


class ServerConnection(XmlStream):

	def connectionMade(self):
		#Send start stream
		XmlStream.connectionMade(self)

	def onDocumentStart(self, rootElement):
		XmlStream.onDocumentStart(self, rootElement)
		XmlStream.send(self, '<?xml version="1.0" encoding="utf-8"?><root>')
		#logging.debug('Document start received')
		manager.client_connected(self)

	def onElement(self, element):
		#logging.debug('Element received')
		XmlStream.onElement(self, element)
		m = message.Message(message = element)
		manager.process_message(m, self)

	def connectionLost(self, reason):
		XmlStream.connectionLost(self, reason)
		manager.client_disconnected(self)

	def send_message(self, m):
		#logging.debug('Sending %s', m.to_xml())
		XmlStream.send(self, m.to_xml())
