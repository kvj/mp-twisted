#!/usr/bin/env python
try:
	from pysqlite2 import dbapi2 as sqlite3
except:
	import sqlite3

import re
import logging

class Index:

	def __init__(self, name, table_name, unique = False, *args):
		self.name = name
		self.table_name = table_name
		self.cols = []
		self.directions = []
		self.unique = unique
		for arg in args:
			self.add_column(arg)

	def add_column(self, name, direction = 'asc'):
		self.cols.append(name.lower())
		self.directions.append(direction.lower())

	def get_create_index_sql(self):
		cols_sql = []
		for i, col_name in enumerate(self.cols):
			cols_sql.append('"%s" %s' % (col_name, self.directions[i]))
		uniq = ''
		if self.unique:
			uniq = ' unique'
		result = 'create%s index %s on %s (%s)'	 % (uniq, self.name, self.table_name, ', '.join(cols_sql))
		return result

class Table:

	def __init__(self, name):
		self.name = name
		self.cols = {}
		self.primary_key = None

	def add_id(self, name):
		self.add_column(name, 'INTEGER', True, True)
		self.set_primary_key(name)

	def add_column(self, name, type = 'TEXT', not_null = False, auto_inc = False, default = None):
		self.cols[name.lower()] = (type, not_null, auto_inc, default)

	def set_primary_key(self, name):
		self.primary_key = name.lower()

	def get_create_col_sql(self, col_name):
		col = self.cols[col_name]
		auto_inc = ''
		not_null = ''
		pk = ''
		default = ''
		if col[3]:
			default = ' DEFAULT %s' % (col[3])
		if self.primary_key == col_name:
			pk = ' PRIMARY KEY'
		if col[2] and self.primary_key == col_name:
			auto_inc = ' AUTOINCREMENT'
		if col[1]:
			not_null = ' NOT NULL'
		return '"%s" %s%s%s%s%s' % (col_name, col[0], not_null, pk, auto_inc, default)


	def get_create_table_sql(self):
		rows_sql = []
		for col_name in self.cols.keys():
			rows_sql.append(self.get_create_col_sql(col_name))
		result = 'create table %s (%s)'	 % (self.name, ', '.join(rows_sql))
		return result

class Database:

	def __init__(self, path):
		self.path = path
		self.tables = {}
		self.indexes = {}

	def add_table(self, table):
		self.tables[table.name] = table

	def add_index(self, index):
		self.indexes[index.name] = index

	def verify_schema(self):
		conn, c = self.open_cursor()
		sql_lines = []
		try:
			#debug table structure
			#c.execute('select * from sqlite_master')
			#logging.debug('DB: %s', c.fetchall())

			#Check tables first
			tnames = {}
			c.execute('''select name, sql from sqlite_master
					  where type='table' ''')
			for row in c:
				if row[0].startswith('sqlite_'):
					continue
				#logging.debug('Found existing table %s', row[0])
				tnames[row[0].lower()] = row[1]
			#logging.debug('Check tables to create... %s', self.tables.keys())
			for name in set(self.tables.keys()).difference(tnames.keys()):
				#All new tables here
				table = self.tables[name]
				logging.debug('Creating table %s', name)
				sql_lines.append(table.get_create_table_sql())
			#logging.debug('Check tables to remove... %s', tnames)
			for name in set(tnames.keys()).difference(self.tables.keys()):
				#All tables to remove
				#Try to find and drop all indexes
				c.execute('''select name from sqlite_master
						  where type='index' and tbl_name=?''', (name, ))
				for row in c:
					logging.debug('Dropping index %s', row[0])
					sql_lines.append('drop index %s' % (row[0]))
				#Drop table
				logging.debug('Dropping table %s', name)
				sql_lines.append('drop table %s' % (name))
			#logging.debug('Check tables to alter...')
			for name in set(tnames.keys()).intersection(self.tables.keys()):
				table = self.tables[name]
				#Try to append new rows to existing table

				#First, found all existing rows
				c.execute('select * from %s' % (name))
				cols = []
				for col in c.description:
					#logging.debug('Existing row %s of %s', col[0].lower(), name)
					cols.append(col[0].lower())

				#Find all new rows
				for col_name in set(table.cols.keys()).difference(cols):
					logging.debug('Adding new row %s to %s', col_name, name)
					sql_lines.append('alter table %s add %s' % (name, table.get_create_col_sql(col_name)))
			#Execute all lines first

			for line in sql_lines:
				logging.debug('SQL: %s', line)
				c.execute(line)
			sql_lines = []
			#Check all existing indexes
			inames = {}
			c.execute('''select name from sqlite_master
					  where type='index' ''')
			for row in c:
				if row[0].startswith('sqlite_'):
					continue
				logging.debug('Found existing index %s', row[0])
				inames[row[0].lower()] = row[0]

			#logging.debug('Check indexes to create... %s', self.indexes.keys())
			for name in set(self.indexes.keys()).difference(inames.keys()):
				#All new tables here
				index = self.indexes[name]
				logging.debug('Creating index %s', name)
				sql_lines.append(index.get_create_index_sql())
			#logging.debug('Check indexes to remove... %s', inames)
			for name in set(inames.keys()).difference(self.indexes.keys()):
				#All indexes to remove
				logging.debug('Dropping index %s', name)
				sql_lines.append('drop index %s' % (name))

				#Try to execute all statements
			for line in sql_lines:
				logging.debug('SQL: %s', line)
				c.execute(line)
			self.commit(conn)
			return True
		except Exception, err:
			logging.error('Error verifiying schema %s', err)
			self.rollback(conn)
		return False

	def open_cursor(self):
		try:
			conn = sqlite3.connect(self.path)
			cursor = conn.cursor()
			return (conn, cursor)
		except Exception, err:
			logging.error('Error opening connection %s', err)
			return (None, None)

	def add_cursor(self, conn):
		try:
			cursor = conn.cursor()
			return cursor
		except Exception, err:
			logging.error('Error adding cursor %s', err)
			return None

	def commit(self, connection):
		if not connection:
			return
		try:
			connection.commit()
			connection.close()
		except:
			pass

	def rollback(self, connection):
		if not connection:
			return
		try:
			connection.rollback()
			connection.close()
		except:
			pass
