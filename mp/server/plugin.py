#!/usr/bin/env python

from mp import message
from mp.server import manager
import logging
import time

class Plugin:

	global_id = 0

	def next_id(self, src, keys):
		end = 1
		result = src[:end].lower()
		while result in keys:
			end = end+1
			result = src[:end].lower()
			if end>len(src):
				self.global_id = self.global_id+1
				result = src+str(self.global_id).lower()
		return result

	def get_list_item(self, _list, key):
		result = None
		for id in _list:
			if id.startswith(key):
				if not result:
					result = _list[id]
				else:
					return None
		return result

	def time_to_iso(self, t):
		if not t:
			return None
		try:
			tm = time.localtime(float(t))
			return time.strftime('%Y-%m-%dT%H:%M:%S', tm)
		except Exception, err:
			logging.exception('Error while converting to ISO: %s', err)
		return None

	def send_error(self, error_message, in_reply = None, in_connection = None):
		m = message.Message('error')
		m.set('text', error_message)
		if in_reply and in_reply.id:
			m.id = in_reply.id
		logging.error('Plugin has an error: %s', error_message)
		if in_connection:
			in_connection.send_message(m)
		else:
			manager.deliver_message(self, m)

	def send_ok(self, ok_message, in_reply = None, in_connection = None):
		m = message.Message('ok')
		if ok_message:
			m.set('text', ok_message)
		if in_reply and in_reply.id:
			m.id = in_reply.id
		if in_connection:
			in_connection.send_message(m)
		else:
			manager.deliver_message(self, m)

	def send_progress(self, error_message):
		m = message.Message('progress')
		m.set('text', error_message)
		manager.deliver_message(self, m)

	def send_message(self, message):
		manager.deliver_message(self, message)

	def get_setting(self, name, default):
		if name in self.settings:
			return self.settings[name]
		return default

	def get_intsetting(self, name, default):
		if name in self.settings:
			return int(self.settings[name])
		return default

	def get_boolsetting(self, name, default):
		if name in self.settings:
			value = self.settings[name]
			if value and value.lower() in ['yes', 'true']:
				return True
			return False
		return default
	
	def setting_changed(self, name, value):
		pass

	def new_message_id(self):
		return manager.next_message_id()

	def new_message(self, message, connection):
		pass

	def send_back(self, message, connection):
		manager.deliver_message(self, message, connection)
