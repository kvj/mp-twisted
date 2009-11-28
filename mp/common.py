#!/usr/bin/env python

import logging
import ConfigParser
from mp.network import http

DEFAULT_CONFIG = 'config.ini'
LOG_FORMAT = '%(asctime)s %(levelname)s %(message)s'

def string_to_log_level(string):
	if string == 'DEBUG':
		return logging.DEBUG
	elif string == 'INFO':
		return logging.INFO
	elif string == 'ERROR':
		return logging.ERROR
	return logging.ERROR

config = ConfigParser.RawConfigParser()

def init_config():
	try:
		config.read(DEFAULT_CONFIG)
	except Exception, err:
		logging.error('Error while reading configuration: %s', err)

def init_client():
	init_config()
	try:
		filename = None
		if config.has_option('Client', 'log_file'):
			filename = config.get('Client', 'log_file')
		logging.basicConfig(level = string_to_log_level(config.get('Client', 'log_level')), format = LOG_FORMAT, filename = filename)
	except Exception, err:
		logging.error('Error while configuring logger: %s', err)

def init_server():
	init_config()
	try:
		filename = None
		if config.has_option('Server', 'log_file'):
			filename = config.get('Server', 'log_file')
		logging.basicConfig(level = string_to_log_level(config.get('Server', 'log_level')), format = LOG_FORMAT, filename = filename)
		#Init proxy
		if config.has_option('Server', 'proxy_host'):
			http.proxy_host = config.get('Server', 'proxy_host')
		if config.has_option('Server', 'proxy_port'):
			http.proxy_port = config.getint('Server', 'proxy_port')
		if config.has_option('Server', 'proxy_user'):
			http.proxy_user = config.get('Server', 'proxy_user')
		if config.has_option('Server', 'proxy_pass'):
			http.proxy_pass = config.get('Server', 'proxy_pass')
	except Exception, err:
		logging.error('Error while configuring logger: %s', err)
