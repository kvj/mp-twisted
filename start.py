#!/usr/bin/env python

import logging
import os
import imp
import pkgutil
import sys
import socket

import database

def load_plugins():
    PLUGIN_DIR = '../mp-home/plugins'
    if not hasattr(socket, 'AF_UNIX'):
        logging.error('Unix sockets are unsupported')
    else:
        logging.error('Unix sockets are supported')
    logging.debug('Loading modules from %s...', PLUGIN_DIR)
    if os.path.exists(PLUGIN_DIR):
        modules = os.listdir(PLUGIN_DIR)
        for f in modules:
            logging.debug('load module from %s', f)
            plugin_path = '%s/%s' % (PLUGIN_DIR, f)
            if os.path.isdir(plugin_path):
                try:
                    m = open('%s/manifest' % (plugin_path), 'r')
                    module = m.read().strip()
                    m.close()
                    logging.debug('looking module %s in %s', module, plugin_path)
                    mod_file, mod_path, mod_desc = imp.find_module(module, [plugin_path])
                    if mod_file:
                        sys.path.append(plugin_path)
                        module = imp.load_module(module, mod_file, mod_path, mod_desc)
                        if module:
                            module.test_module('Magic!')
                        mod_file.close()
                except Exception as err:
                    logging.error('cant load plugin %s %s', f, err)
    else:
        logging.info('Plugins not found')

def test_db():
    db = database.Database('db/master.db')
    t1 = database.Table('t2')
    t1.add_column('id', 'integer', auto_inc = True)
    t1.add_column('name')
    t1.add_column('password')
    t1.add_column('info2', default = "'empty'")
    t1.set_primary_key('id')
    db.add_table(t1)
    i1 = database.Index('indx_t2', 't2')
    i1.add_column('name')
    db.add_index(i1)
    i2 = database.Index('indx3_t2', 't2')
    i2.add_column('name')
    i2.add_column('password', 'desc')
    #i2.unique = True
    db.add_index(i2)

    db.verify_schema()
    conn, c = db.open_cursor()
    try:
        c.execute('insert into t2 (name, password, info2) values (?, ?, ?)', ('kostya', 'wellcome', 'some info'))
        logging.debug('Inserted id: %i', c.lastrowid)
        db.commit(conn)
    except Exception as err:
        db.rollback(conn)
        logging.error('Error inserting data to DB %s', err)

if __name__ == '__main__':
    logging.basicConfig(level = logging.DEBUG)
    test_db()
