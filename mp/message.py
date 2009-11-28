#!/usr/bin/env python

from twisted.words.xish.domish import Element
import logging

class Message:

	_messageId = 1

	def __init__(self, name = None, message = None):
		self.name = name
		self.properties = {}
		self.id = Message._messageId
		Message._messageId = Message._messageId+1
		if message:
			self.parse_xml(message)

	def parse_xml(self, message):
		if message.hasAttribute('id'):
			self.id = message['id']
		self.name = message.name
		for el in message.children:
			if el.getAttribute('type', '') == 'message':
				self.set(el.name, Message(None, el))
			elif el.getAttribute('type', '') == 'list':
				arr = []
				for itm in el.children:
					if itm.getAttribute('type', '') == 'message':
						arr.append(Message(None, itm))
					else:
						arr.append(unicode(itm))
				self.set(el.name, arr)
			else:
				self.set(el.name, unicode(el))

	def set(self, field, value):
		self.properties[field] = value

	def get(self, field, default = None):
		if field not in self.properties:
			return default
		value = self.properties[field]
		if value == '':
			return None
		return self.properties[field]

	def keys(self):
		return self.properties.keys()

	def _to_value(self, value):
		if isinstance(value, int):
			return unicode(value)
		if isinstance(value, unicode):
			return value
		return unicode(value, 'utf-8')


	def to_xml(self, internal = False):
		result = Element(('', self.name))
		result['type'] = 'message'
		if not internal:
			if self.id:
				result['id'] = unicode(self.id)
		for field in self.properties.keys():
			value = self.get(field)
			if isinstance(value, list):
				el = result.addElement(field)
				el['type'] = 'list'
				for item in value:
					if isinstance(item, Message):
						el.addChild(item.to_xml(True))
					else:
						el.addElement('item', content = self._to_value(item))
			elif isinstance(value, Message):
				result.addChild(value.to_xml(True))
			else:
				if value:
					result.addElement(field, content = self._to_value(value))
		if internal:
			return result
		return result.toXml()

def response_message(m, name = None):
	mess = Message(m.name)
	if m.id:
		mess.id = m.id
	if name:
		mess.name = name
	if m.get('via'):
		mess.set('net', m.get('via'))
	return mess
