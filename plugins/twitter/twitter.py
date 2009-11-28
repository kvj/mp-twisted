import logging
from mp.network import http
from mp.server import plugin, database
from mp import message
from twisted.internet import reactor
from twisted.words.xish.domish import Element
from twisted.internet.task import LoopingCall
import time

class TwitterPlugin(plugin.Plugin):
	
	def activate(self):
		logging.debug('Twitter is active %s %s', self.name, self.settings)

		#Init database
		try:
			# messages = database.Table('messages')
			# messages.add_id('id')
			# messages.add_column('id_message')
			# messages.add_column('sender')
			# messages.add_column('jid')
			# messages.add_column('thread')
			# messages.add_column('date_received')
			# messages.add_column('unread', 'INTEGER', default = 1)
			# messages.add_column('body')
			# self.db.add_table(messages)
			if not self.db.verify_schema():
				return False
		except Exception, err:
			logging.exception('Error while verifying schema: %s', err)
			return False
		return True

	def deactivate(self):
		logging.debug('Twitter %s is stopped', self.name)

def get_name():
	return 'twitter'

def get_description():
	return 'Twitter plugin'

def get_class():
	return TwitterPlugin
