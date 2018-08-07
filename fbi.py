# 
# Script to explore the connections and get objects via Graph API from Facebook
# Project: MT Social BI/SMCC pilot
# 201501030
# Created by Szucsan Laszlo
#
# Run: 
#    ssh <USER>@172.28.164.101
#    [<USER>@c3po ~]# sudo su - facebook
#    [facebook@c3po ~]# cd <FACEBOOK HOME>
#    [facebook@c3po]# nohup python -u fbi.py (-i) > nohup.out &
#            -i ------> used in special cases to initialize the program (drop backend database, delete hdfs and start a new download)
#
# Input files:
#      fbi.edges.txt    - Listed connections of a facebook object according to graph api reference
#                       - usage indicator (Y/N) Y - active, N - do not use
#                       - priorization of request (lower is important)
#                       - expiry time of request (minutes)
#      fbi.fields.txt   - not used yet. attributes of facebook objects
#      fbi.objects.txt  - Listed facebook objects
#                       - priorization of request (lower is important)
#                       - expiry time of request (minutes)
#      fbi.access_token - access token to create graph api connection   
#                       - in case of TOKEN_TYPE = 'FBAPP' - short live token of SMCC application generated from https://developers.facebook.com/tools/explorer/
#                       - in case of TOKEN_TYPE = 'GRAPHAPI' - short live token of Graph Api application generated from https://developers.facebook.com/tools/explorer/
#                       - in case of TOKEN_TYPE = 'GRAPHAPI-PARALLEL' - fbi.access_token.<worker process id> files will be used. Each files contain short live access token of Graph Api application generated from https://developers.facebook.com/tools/explorer/
#                         graph api application short live tokens must be updated in every hours
# Output files:
#      fbi.log          - application debug and error log
#      fbi.result.log   - Logging status and properies of processed request 
#      OUTPUT_DIR/<object_id_timestamp> - saving answer of successful requests. (local files or/and HDFS upload)
#
#
#
# Components:
#       fbi.py - This file
#       fbi.db - backend sqlite database to store graph api request status
#       fbi.status.sh - log analyser - need to be updated 
#


import facebook  # pip install facebook-sdk
from facepy.utils import get_extended_access_token
#from facepy import GraphAPI
import json
import jsontree
import datetime
import os
import errno
from datetime import datetime, timedelta
import logging
import sys
import cPickle
import multiprocessing
#import pywebhdfs		#pywebhdfs was replaced with hdfs because of kerberos authentication integration
import hdfs
from hdfs import Config
from hdfs import InsecureClient
from hdfs.ext.kerberos import KerberosClient
from hdfs.util import HdfsError

import time
import requests
import dataset
#from pywebhdfs.webhdfs import PyWebHdfsClient
#from pywebhdfs.webhdfs import errors
import random
import shutil
import glob
from fbicfg import *
# import pydoop #Other kind of HDFS client but must be installed and configured

# graph api request class to store properties
class Request:

      def __init__(self, ref, level, type, parent_id, parent_type, root, root_type, priority):
	    if ref.count('/') == 1:
		fbo_type = 'fb_edge'
            else:
		fbo_type = 'fb_object'
            self.ref = ref
            self.id = ref
            self.level = level
            self.type = type
            self.fbo_type = fbo_type
            self.parent_id = parent_id
            self.parent_type = parent_type
            self.root = root
            self.root_type = root_type
            self.page = 1
            self.status = 'INIT'
            self.response_size = 0
            self.download_time = MIN_DATETIME.strftime(DATE_FMT)
            self.expiry_time = MIN_DATETIME.strftime(DATE_FMT)
            self.priority = priority

# Input parameters of facebook objects - structure of fbi.objects.txt
class Object:

      def __init__(self, obj, active, expiry_minutes, priority):
            self.obj = obj
            self.active = active
            self.expiry_minutes = expiry_minutes
            self.priority = priority

# Input parameters of facebook edges - structure of fbi.edges.txt
class Edge:

      def __init__(self, obj, edge, active, expiry_minutes, priority):
            self.obj = obj
            self.edge = edge
            self.active = active
            self.expiry_minutes = expiry_minutes
            self.priority = priority

# Input parameters: attributes of facebook object  - structure of fbi.fields.txt
# Not used, will be useful to identifiy the type for a given facebook objectID
class Field:

      def __init__(self, obj, field, type):
            self.obj = obj
            self.field = field
            self.type = type

# Get the type of a downloaded facebook json object
# Called from worker and worker->function get_id
def get_type(o):
      try:
            o['metadata']['type']
      except:
            try:
                  o['type']
            except:
                  return('unknown')
            else:
                  return(o['type'])
      else:
            return(o['metadata']['type'])


# Get the ID of a downloaded facebook object
# Called from worker
def get_id(o):
      try:
            o['id']
      except:
            logging.info('Unknown id for object type: ' + get_type(o))
            return('unknown')
      else:
            return(o['id'])

# Check and fill field which is not available
# Called from worker->save_meta
def chk_field(f, d):
      try:
            f[d]
      except:
            return("")
      else:
            return(f[d])

# Function to check validity of content for received data from facebook
# Called from worker
# FIX
def check_result(t):
      if (len(t) == 12 or len(t) < 1000) and t.find('"data": []')>-1:
            return('EMPTY')
      return('OK')

# Function to dump json obj on display
# Not used - only for debugging
def pp(o):
      print json.dumps(o, indent=1)

# Function to replace null value
def nvl(p1, p2):
      if p1 == '' or p1 == 'unknown':
            if p2 <> '':
                  return(p2)
            else:
                  return('unknown')
      else:
            return(p1)

# Calculate sum value in list for the last 10 minutes
def sum_last10(cntl):
      i = 0
      sm = 0
      while i < 9 and i < len(cntl):
            sm = sm + cntl[i]
            i = i + 1
      return(sm)

# Calculate sum value in list for the last 10 minutes
def sum_last60(cntl):
      i = 0
      sm = 0
      while i < 59 and i < len(cntl):
            sm = sm + cntl[i]
            i = i + 1
      return(sm)

# Function to load metadata
# Edges are used to lookup next objects
# Fields are not used yet.
# Called from main program at initialization
def load_meta():

      f1 = open('fbi.objects.txt', 'r')
      lines = f1.readlines()
      for line in lines:
            p = line.split()
            objects.insert(0, Object(p[0], p[1], int(p[2]), int(p[3])))
            logging.debug(
                "load_meta - objects: " + p[0] + ' ' + p[1] + ' ' + p[2] + ' ' + p[3])
      f1.close()

      f1 = open('fbi.edges.txt', 'r')
      lines = f1.readlines()
      for line in lines:
            p = line.split()
            if p[2] == 'Y':
                  edges.insert(0, Edge(p[0], p[1], p[2], int(p[3]), int(p[4])))
                  logging.debug(
                      "load_meta - edges: " + p[0] + ' ' + p[1] + ' ' + p[2] + ' ' + p[3] + ' ' + p[4])
      f1.close()

      f1 = open('fbi.fields.txt', 'r')
      lines = f1.readlines()
      for line in lines:
            p = line.split()
            fields.insert(0, Field(p[0], p[1], p[2]))
      f1.close()
# END load_meta

# Function to collect meta information from facebook objects into text file (if function is enabled)
# Called from worker
def save_meta(o, ot):
      if ot <> 'unknown':
            f1 = open('new_fields.txt', 'a')
            f2 = open('new_edges.txt', 'a')
            try:
                  o['metadata']['connections']
            except:
                  return("")
            try:
                  o['metadata']['fields']
            except:
                  return("")

            for con in o['metadata']['connections']:
                  f2.write(ot + "\t" + con + "\tNo\n")
            for field in o['metadata']['fields']:
                  f1.write(ot + "\t" + chk_field(field, 'name') + "\t" +
                           chk_field(field, 'type') + "\t" + chk_field(field, 'description') + "\n")
            f1.close()
            f2.close()
# END save_meta

# Function to get and add connected objects to object list
# Called from worked
def add_connected_objs(t, o, nq):
      p1 = t.find('"id":')
      while p1 > 0:
            p2 = t[p1:].find('\n')
            s = t[p1:p1 + p2].replace('"id":', ' ', 1)
            id = s[s.find('"') + 1:s.replace('"', ' ', 1).find('"')]

            # Send to qmanager
            nq.put(Request(id, o.level + 1, '',
                           o.id, o.type, o.root, o.root_type, OBJ_PRIORITY))
            t = t[p1 + p2:]
            p1 = t.find('"id":')

# END add_connected_objs

# Function to add connected edges to object list
# Called from worker
def add_connected_edges(o, nq):
      for e in edges:
            # If edge belongs to given type of object
            if o.type == e.obj:
                  # Send to qmanager
                  nq.put(Request(o.id + '/' + e.edge, o.level +
                                 1, e.edge, o.id, o.type, o.root, o.root_type, e.priority))

# END add_connected_edges

# Function to calculate the percentage of older posts/all posts
# Called from worker
def chk_created_date(t, mdate):
      p1 = t.find('"created_time":')
      mdatef = mdate.strftime('%Y-%m-%dT%H:%M:%S+000')
      cnte = 0
      cnta = 0
      while p1 > 0:
            p2 = t[p1+20:].find('"')
            s = t[p1:p1 + p2+20].replace('"created_time":', ' ', 1)
            id = s[s.find('"') + 1:s.replace('"', ' ', 1).find('"')]
            if id < mdatef:
                cnte = cnte + 1
            cnta = cnta + 1
            t = t[p1 + p2:]
            p1 = t.find('"created_time":')
      logging.debug(
                      "worker(" + str(os.getpid()) + ") - chk_created_date  " + str(cnte))
      logging.debug(
                      "worker(" + str(os.getpid()) + ") - chk_created_date  " + str(cnta))
      logging.debug(
                      "worker(" + str(os.getpid()) + ") - chk_created_date  " + str(mdatef))

      if cnta == 0:
            return(0.0)
      else:
      	    logging.debug(
                      "worker(" + str(os.getpid()) + ") - chk_created_date  " + str(float(cnte)/float(cnta)))
      	    return (float(cnte)/float(cnta))

# END chk_created_date

# Function to save result in the given local folder and to upload to HDFS Server
# Called from uploader
def send_file(fn, dn, s):
      if SAVE_LOCAL:  # Save on local disk
            f = LOCAL_OUTPUT_DIR + dn + '/' + fn
            d = LOCAL_OUTPUT_DIR + dn + '/'
            if (d <> '') and (not os.path.exists(d)):
                  os.makedirs(d)
            f1 = open(f, 'w')
            f1.write(s)
            f1.close()

      if USE_HDFS:  # Send to HDFS Server via webhdfs api
            f = REMOTE_OUTPUT_DIR + dn + '/' + fn
            d = REMOTE_OUTPUT_DIR + dn + '/'
            # Check and create destination folder if it is necessary
            try:
		  hdfs.status(d)
	    except Exception as e:
		  if (e.args[0]).encode('latin-1').find('File does not exist') >= 0:
	          	hdfs.makedirs(d)
            except:
                  logging.error('uploader(' + str(os.getpid()) + '): error during creating directory on HDFS, dirname: ' + d)
                  logging.exception('')
                  return False 
            # Try to send file
            try:
                  hdfs.write(f, s, overwrite=False)
		  logging.info('uploader(' + str(os.getpid()) + '): creating file: ' + f)
            except:
                  logging.error('uploader(' + str(os.getpid()) + '): error during creating file on HDFS, filename: ' + f)
                  logging.exception('')
                  return False 
      return True 
# END send_file


# Function to collect result in the given local folder
# Called from worker
def save_file(fn, dn, s):
      fn = dn + fn

      if (dn <> '') and (not os.path.exists(dn)):
            os.makedirs(dn)
      f1 = open(fn, 'a')
      f1.write(s)
      f1.close()

# END save_file


# Function to save result in the given folder
def log(ro):
      f1 = open(LOG_FILE, 'a')
      f1.write('%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' % (str(ro.download_time), REMOTE_OUTPUT_DIR, ro.ref, ro.id, str(ro.page), ro.fbo_type, nvl(
          ro.type, 'unknown'), nvl(ro.parent_id, 'unknown'), nvl(ro.parent_type, 'unknown'), nvl(str(ro.response_size), '0'), nvl(str(ro.level), '-1'), ro.status))
      f1.close()

# Function to insert or update request data in the database
# Called from qmanager

def backup_request(rt, ro):
      if rt.find_one(rid=ro.id) == None:
            rt.insert(dict(rid=ro.id, ref=ro.ref, level=ro.level, type=ro.type, fbo_type=ro.fbo_type, parent_id=ro.parent_id, parent_type=ro.parent_type, root=ro.root, root_type=ro.root_type, 
                           page=ro.page, status=ro.status, response_size=ro.response_size, download_time=ro.download_time, expiry_time=ro.expiry_time, priority=ro.priority))
      else:
            if ro.status <> 'INIT':
            	  rt.update(dict(rid=ro.id, status=ro.status, type=ro.type, response_size=ro.response_size, page=ro.page,
                           download_time=ro.download_time, expiry_time=ro.expiry_time, priority=ro.priority), ['rid'])


# Function to insert request for SSO users in the database						   
# Called from qmanager

def add_sso_user(rt, userid):
    row = rt.find_one(rid=userid)
    for o in objects:
            if o.obj == 'user' and o.active == 'Y':
                  usr_priority = o.priority	

    ro = Request(userid, 0, 'user', '', '', userid, 'user', usr_priority)
    if row == None:
	    rt.insert(dict(rid=ro.id, ref=ro.ref, level=ro.level, type=ro.type, fbo_type=ro.fbo_type, parent_id=ro.parent_id, parent_type=ro.parent_type, root=ro.root,
               root_type=ro.root_type, page=ro.page, status=ro.status, response_size=ro.response_size, download_time=ro.download_time, expiry_time=ro.expiry_time, priority=ro.priority))
	    logging.debug('add_sso_user(' + str(os.getpid()) + '): - add SSO user request: ' +  userid)	
    else:
	    if row['root'] <> userid or row['root_type'] <> 'user' or row['level'] <> 0 or row['priority'] <> usr_priority: 
			rt.update(dict(rid=ro.id, status=ro.status, level=ro.level, type=ro.type, response_size=ro.response_size, page=ro.page, root=ro.root, root_type=ro.root_type,
                           download_time=ro.download_time, expiry_time=ro.expiry_time, priority=ro.priority), ['rid'])
			logging.debug('add_sso_user(' + str(os.getpid()) + '): - update SSO user request: ' +  userid)					   
						   
# Separated process to upload files which were saved in last hour.
def uploader():
	 logging.info('uploader(' + str(os.getpid()) + '): - STARTED')
# MAIN loop:
	 while (not os.path.isfile('stop')):
    			time.sleep(10)
			#Block 1 - collecting and upload downloaded jsons
			for dp, dn, filenames in os.walk(TEMP_DIR):
				for f in filenames:
					p = os.path.join(dp, f) 
					if datetime.fromtimestamp(os.path.getmtime(p)) < datetime.now().replace(minute=0, second=0, microsecond=0):
						with open (p, "r") as mf:
							if(send_file(f, dp.replace(TEMP_DIR,''), mf.read())):
								os.remove(p)
			
			#Block 2 - download daily SSO facebook login users
			if USE_HDFS:
				# Latest local file 
				for dp_local, dn_local, filenames_local in os.walk(LOCAL_SSO_STAGING_DIR):
					try:
						MAX_FILENAME1 = max(filenames_local)
					except:
						MAX_FILENAME1 = None
					
				for dp_local, dn_local, filenames_local in os.walk(LOCAL_SSO_ARCHIVE_DIR):
					try:
						MAX_FILENAME2 = max(filenames_local)
					except:
						MAX_FILENAME2 = None

				MAX_FILENAME = max(MAX_FILENAME1,MAX_FILENAME2)
				
				# Copy file from HDFS to local	
				try:
					flist = hdfs.list(REMOTE_SSO_INPUT_DIR)
					for f in flist:
						if f > MAX_FILENAME:
							try:
								with hdfs.read(REMOTE_SSO_INPUT_DIR + f) as reader:
									s = reader.read()
								save_file(f, LOCAL_SSO_STAGING_DIR, s)
								logging.info('uploader('+ str(os.getpid()) + ') - download file from HDFS: ' + f)
							except:
		                  				logging.error('uploader(' + str(os.getpid()) + '): error during reading file: ' + REMOTE_SSO_INPUT_DIR + f)
                  						logging.exception('')
				except:
	                  		logging.error('uploader(' + str(os.getpid()) + '): error during listing HDFS directory: ' + REMOTE_SSO_INPUT_DIR)
                  			logging.exception('')
			#Block 3 - Clean up archive directory						
			for dp_local, dn_local, filenames_local in os.walk(LOCAL_SSO_ARCHIVE_DIR):
				for f in filenames_local:
					if f < 'SSO_LOGINS_' + str((datetime.now()-timedelta(SSO_RETENTION_DAYS)).strftime('%Y%m%d')):
						try:
							 os.remove(dp_local + f)
							 logging.info('uploader('+ str(os.getpid()) + ') - clean up archive directory, deleting file: ' + f)	
						except:
							 logging.error('uploader('+ str(os.getpid()) + ') - error during deleting file in archive directory, filename: ' + f)	
							 logging.exception('')
			#Block 4 - Waiting for	
			h1 = datetime.now().hour
			while datetime.now().hour == h1 and (not os.path.isfile('stop')):
				time.sleep(10)
							 
	 logging.info('uploader(' + str(os.getpid()) + '): - STOPPED AND QUIT')
	 return
# END uploader


# Separated process to manage real-time request queue.
#       - Control realtime request queue and send new requests to workers
def rtqmanager(rq):
      # INIT:
      cntl = []
      cnt = 0
      lm = 0
      sm = 0
      no = Request('', 0, '', '', '', '', '',1)

      logging.info('rtqmanager(' + str(os.getpid()) + '): - STARTED')

      # MAIN loop:
      while (not os.path.isfile('stop')):
            fl = glob.glob(LOCAL_RT_INPUT_DIR+'*.txt')
            if len(fl) == 0:
                  time.sleep(1)
            else:
	    	  sm = sum_last10(cntl)  #sum calls
 		  if sm + cnt >= MAX_WCALL*RTW_PARALLEL or rq.qsize() >= MAX_RQSIZE:
                          time.sleep(1)
		  else:
			for fn in fl:
				f1 = open(fn, 'r')
      				lines = f1.readlines()
      				for line in lines:
            				p = line.split()
            				logging.debug(
                				'rtqmanager(' + str(os.getpid()) + '): - ' + p[0])
					f1.close()

					no = Request(p[0], 0, '', '', '', p[0], 'user', 100)
					ref = p[0]

	    				if ref.count('/') == 1:
						no.type = ref[ref.find('/')+1:]
            				else:
						no.type = ''
                              		#no.ref = p[0]
                              		#no.id = p[0]
                              		#no.level = r['level']
                              		#no.type = r['type']
                              		#no.fbo_type = r['fbo_type']
                              		#no.parent_id = r['parent_id']
                              		#no.parent_type = r['parent_type']
                              		#no.root = p[0]
                              		#no.page = r['page']
                              		#no.status = r['status']
                              		#no.response_size = r['response_size']
                              		#no.download_time = r['download_time']
                              		#no.expiry_time = r['expiry_time']
                              		#no.priority = 1
                              		rq.put(no)
                              		cnt = cnt + 1
                     		shutil.move(fn,LOCAL_RT_INPUT_DIR+'archive')
				#if too many objects were in the file then exit from the loop
				if sm + cnt >= MAX_WCALL*RTW_PARALLEL or rq.qsize() >= MAX_RQSIZE:
					break
	    m = datetime.now().minute
            # Count the request for every minute, if the minute changed store into
            # the list and reset the counter. Logging in every minutes.
            if m <> lm:
                  cntl.insert(0, cnt)
                  logging.info(
                      'rtqmanager(' + str(os.getpid()) + '): - request in last minute:  ' + str(cnt))
                  logging.info(
                      'rtqmanager(' + str(os.getpid()) + '): - request in last 10 minutes:  ' + str(sm))
                  logging.info(
                      'rtqmanager(' + str(os.getpid()) + '): - requestq: ' + str(rq.qsize()))
                  cnt = 0
            lm = m
            # If nothing to do, wait a second
	    
      # EXIT:

      # Empty request queue
      while not rq.empty():
            no = rq.get()

      logging.info('rtqmanager(' + str(os.getpid()) + '): - STOPPED AND QUIT')
      return

# END rtqmanager

# Separated process to manage request queue.
#       - Receive results and new requests from workers .
#       - Handling backend database
#       - Control request queue and send new requests to workers
def qmanager(nq, rq):
      # INIT:
      cntl = []
      cnt = 0
      lm = 0
      MAX_CALL60 = MIN_CALL60_LIMIT
      no = Request('', 0, '', '', '', '', '', 1)

      logging.info('qmanager(' + str(os.getpid()) + '): - STARTED')
      # db = dataset.connect('mysql://root:@localhost/fbi')
      db = dataset.connect('sqlite:///fbi.db')
      # reset request statuses which were not processed during last stopping
      res = db.query(
          'UPDATE request set status="INIT" WHERE status = "QUEUED"')
      reqtab = db['request']

      # Logging request statuses
      logging.info('qmanager(' + str(os.getpid()) + '): - init - database rows: ' + str(len(reqtab)))
      res = db.query('SELECT status, COUNT(*) c FROM request GROUP BY status')
      for row in res:
            logging.info(
                'qmanager(' + str(os.getpid()) + '): - init - Number of ' + row['status'] + ': ' + str(row['c']))

      # MAIN loop:
      while (not os.path.isfile('stop')):
            sm = cnt + sum_last10(cntl)   #sum calls
            sm60 = cnt + sum_last60(cntl) #sum calls for last 60 minutes.
			
	    # 1st block
	    # Processing SSO facebook user ID's in LOCAL_SSO_STAGING_DIR and loading into the Request list (fbi.db)	
	    for dp, dn, filenames in os.walk(LOCAL_SSO_STAGING_DIR):
			    fn_sorted = sorted(filenames)
			    for f in fn_sorted:
					if (os.path.isfile('stop')):
						break
					i = 0
					p1 = os.path.join(dp, f)
					f1 = open(p1, 'r')
					lines = f1.readlines()
					db.begin()
					for line in lines:
						 p = line.split()
						 add_sso_user(reqtab, p[0])  #Loading into the database
						 i = i+1
					user_count = i
					db.commit()
					f1.close()
					
					#move file to archive	
					shutil.move(p1,LOCAL_SSO_ARCHIVE_DIR + f)	
					logging.info('qmanager(' + str(os.getpid()) + '): - SSO file loaded from staging directory and moved to archive: ' + f)							  
				        # Calculate the hourly request rate limit accodring to current facebook rate policy, force the lower and upper limit by parameter 		
			                if MAX_CALL60_LIMIT < user_count * FB_REQ_RATE and MAX_CALL60_LIMIT > 0:
					         MAX_CALL60 = MAX_CALL60_LIMIT
			                else:	
					         if MIN_CALL60_LIMIT > user_count * FB_REQ_RATE and MIN_CALL60_LIMIT > 0:
						 	MAX_CALL60 = MIN_CALL60_LIMIT
						 else:
							MAX_CALL60 = user_count * FB_REQ_RATE
				 
            # 2nd block
	    # Receiving and storing new request
            i = 0
            nqs = nq.qsize()
            db.begin()
            while i < MAX_BULKSIZE and i < nqs:
                  no = nq.get()
                  backup_request(reqtab, no)
                  i = i + 1
            db.commit()
			
			# 3rd block
			# Feeding worker
            if ((sm < MAX_CALL or MAX_CALL == 0) and (sm60 < MAX_CALL60 or MAX_CALL60 == 0) and rq.qsize() <= MAX_RQSIZE - INC_RQSIZE):
                  res = db.query(
                      'SELECT * FROM request WHERE status = "INIT" union SELECT * FROM request WHERE status = "OK" and expiry_time<strftime("%Y%m%d%H%M%S",datetime("now","localtime")) order by status,expiry_time,level,priority LIMIT ' + str(INC_RQSIZE))
                  if res <> None:
                        db.begin()
                        for r in res:
                              no.ref = r['ref']
                              no.id = r['rid']
                              no.level = r['level']
                              no.type = r['type']
                              no.fbo_type = r['fbo_type']
                              no.parent_id = r['parent_id']
                              no.parent_type = r['parent_type']
                              no.root = r['root']
                              no.root_type = r['root_type']
                              no.page = r['page']
                              no.status = r['status']
                              no.response_size = r['response_size']
                              no.download_time = r['download_time']
                              no.expiry_time = r['expiry_time']
                              no.priority = r['priority']
                              rq.put(no)
                              reqtab.update(
                                  dict(rid=no.id, status='QUEUED'), ['rid'])
                              cnt = cnt + 1
                        db.commit()
            m = datetime.now().minute
			# 4th block - Logging
            # Count the request for every minute, if the minute changed store into
            # the list and reset the counter
            if m <> lm:
                  cntl.insert(0, cnt)
                  logging.info(
                      'qmanager(' + str(os.getpid()) + '): - request in last minute:  ' + str(cnt))
                  logging.info(
                      'qmanager(' + str(os.getpid()) + '): - request in last 10 minutes:  ' + str(sm))
		  logging.info(
                      'qmanager(' + str(os.getpid()) + '): - request in last 60 minutes:  ' + str(sm60))
                  logging.info('qmanager(' + str(os.getpid()) + '): - resultq: ' + str(nq.qsize()) +
                               ' requestq: ' + str(rq.qsize()) + ' database rows: ' + str(len(reqtab)))
                  cnt = 0
            lm = m
			
			# 5th block - waiting
            # If nothing to do, wait a second
            if nq.qsize() < MIN_BULKSIZE or sm >= MAX_CALL or sm60 >= MAX_CALL60:
                  time.sleep(1)

      # End of MAIN LOOP
      # EXIT:
      # Empty request queue
      while not rq.empty():
            no = rq.get()
      # Save resultqueue into the database
      i = 0
      while not nq.empty():
            db.begin()
            while not nq.empty() and i < MAX_BULKSIZE:
                  no = nq.get()
                  backup_request(reqtab, no)
                  i = i + 1
            db.commit()
            i = 0
            logging.info('qmanager(' + str(os.getpid()) + '): - exit - inserted rows: ' +
                         str(MAX_BULKSIZE) + ' remaining rows: ' + str(nq.qsize()))

      # Logging request statuses
      logging.info('qmanager(' + str(os.getpid()) + '): - exit - database rows: ' + str(len(reqtab)))
      res = db.query('SELECT status, COUNT(*) c FROM request GROUP BY status')
      for row in res:
            logging.info(
                'qmanager(' + str(os.getpid()) + '): - exit - Number of ' + row['status'] + ': ' + str(row['c']))
				
      logging.info('qmanager(' + str(os.getpid()) + '): - STOPPED AND QUIT')
      return

# END qmanager

# Several separated processes to download jsons form facebook and process the results
#       - build up a connection and download request
#       - get new object id-s and build new request
#       - build new request from edges which are connected to object
#       - send new request to qmanager
#       - store result in HDFS/local FS
#       - simple paging the requested json file if it is necessary


def worker(nq, rq, rtflag, token_file):
      i = 1
      lm = 0
      counter = 0
      cntl = []
      logging.info('worker(' + str(os.getpid()) + '): STARTED - serving request in realtime: ' + str(rtflag))

      if not(os.path.isfile(token_file)):
            logging.info(
                'worker(' + str(os.getpid()) + '): waiting for token file: ' + token_file)   
            print 'worker(' + str(os.getpid()) + '): waiting for token file: ' + token_file
                   
      while (not os.path.isfile(token_file)) and (not os.path.isfile('stop')): 
            time.sleep(1)
                   
      if os.path.isfile(token_file):
            fat = open(token_file, 'r')
            ACCESS_TOKEN = fat.readline()
            fat.close()
            tokentime = os.path.getmtime(token_file)
            logging.info(
                'worker(' + str(os.getpid()) + '): read token:' + ACCESS_TOKEN)
            logging.info('worker(' + str(os.getpid()) + '): fbi.access_token modification time:' +
                         datetime.fromtimestamp(tokentime).strftime(DATE_FMT))
            #Get long live accesss token if the token belongs to SMCC application
            if TOKEN_TYPE == 'FBAPP':
                  time.sleep(random.randint(0,9))
                  ACCESS_TOKEN = get_extended_access_token(
                       ACCESS_TOKEN, SSO_APP_ID, SSO_SECRET_KEY)[0]
            # Create a connection to the Graph API with your access token
            g = facebook.GraphAPI(ACCESS_TOKEN)
      else:
            logging.info(
                'worker(' + str(os.getpid()) + '): could not find file: ' + token_file)

      while (not os.path.isfile('stop')):
            sm = counter + sum_last10(cntl)   #sum calls
            if (not os.path.isfile('stop')) and (not rq.empty()) and sm < MAX_WCALL:
                  nobj = rq.get()
	          counter = counter + 1
	          pdownload_time = datetime.strptime(nobj.download_time, DATE_FMT).strftime(DATE_FMT) 
                  nobj.download_time = datetime.now().strftime(DATE_FMT)
                  try:
                        obj = g.get_object(
                            nobj.ref, metadata=1, limit=100)  # ,limit=5000
                  except Exception as e:
                        logging.error(
                            'worker(' + str(os.getpid()) + '): g.get_object(' + nobj.ref + ',metadata=1, limit=100)')
                        logging.exception('')
                        nobj.status = 'ERROR'
                        nq.put(nobj)
                        log(nobj)
                        # Quit or wait after errors in GraphAPI connection(expired session, reaching max request limit, etc.)
                        # Waiting for new token
                 
			if (e.args[0]).encode('latin-1').find('Error validating access token') >= 0:
                              rq.put(nobj)
                              logging.info(
                                  'worker(' + str(os.getpid()) + '): WAITING for valid access token')
                              while (not os.path.isfile('stop')):
                                    if os.path.isfile(token_file) and tokentime < os.path.getmtime(token_file):
                                          break
                                    else:
                                          time.sleep(5)
                              if os.path.isfile(token_file):
                                    fat = open(token_file, 'r')
                                    ACCESS_TOKEN = fat.readline()
                                    fat.close()
                                    tokentime = os.path.getmtime(
                                        token_file)
                                    logging.info(
                                        'worker(' + str(os.getpid()) + '): read token:' + ACCESS_TOKEN)
                                    logging.info('worker(' + str(os.getpid()) + '): fbi.access_token modification time:' +
                                                 datetime.fromtimestamp(tokentime).strftime(DATE_FMT))
                                    g = facebook.GraphAPI(ACCESS_TOKEN)
                              else:
                                    logging.info(
                                        'worker(' + str(os.getpid()) + '): could not find file: ' + token_file)
                        # Waiting for 2 minutes
			if (e.args[0]).encode('latin-1').find('Calls to stream have exceeded') >= 0:
                              rq.put(nobj)
                              logging.info(
                                  'worker(' + str(os.getpid()) + '): wait 2 minutes. (GrahAPIError)')
                              i = 0
                              while i < 120 and (not os.path.isfile('stop')):
                                    time.sleep(1)
                                    i = i + 1
                        # Waiting for 2 hours
			if (e.args[0]).encode('latin-1').find('User request limit reached') >= 0:
                              rq.put(nobj)
                              logging.info(
                                  'worker(' + str(os.getpid()) + '): wait 2 hours. (GrahAPIError)')
                              i = 0
                              while i < 2 * 60 * 60 and (not os.path.isfile('stop')):
                                    time.sleep(1)
                                    i = i + 1
                  else:
                        try:
                              s = json.dumps(obj)
                        except:
                              logging.error(
                                  'Error in JSON.dump for result of g.get_object(' + nobj.ref + ',metadata=1)')
                              nobj.status = 'ERROR'
                              nq.put(nobj)
                              log(nobj)
                        else:
                              nobj.type = nvl(get_type(obj), nobj.type)
                              nobj.id = nvl(get_id(obj), nobj.id)
                              nobj.status = check_result(s)
                              page_status = nobj.status
                              j = 1
                              postfix = ''
                              # Set priority and calculate expiry time for facebook. expiry_minutes = 0 means no refresh needed
                              # object
                              if nobj.fbo_type == 'fb_object':
                                    nobj.priority = DEF_PRIORITY
                                    nobj.expiry_time = INF_DATETIME.strftime(DATE_FMT)
                                    # Find the current active object, if the object type was set to inactive then the expire time will be infinity
                                    for o in objects:
                                          if o.obj == nobj.type and o.active == 'Y':
                                                nobj.priority = o.priority
                                                if o.expiry_minutes <> 0:
							nobj.expiry_time = (datetime.strptime(
                                                    		nobj.download_time, DATE_FMT) + timedelta(minutes=o.expiry_minutes)).strftime(DATE_FMT)
                                                break
                              # Calculate expiry time for facebook edge, priority has
                              # already been set in function. There are only active edge types in the edges. expiry_minutes = 0 means no refresh needed
                              # add_connected_edges()
                              if nobj.fbo_type == 'fb_edge':
                                    nobj.expiry_time = INF_DATETIME.strftime(DATE_FMT)
                                    # Find the current object
                                    for e in edges:
                                          if e.obj == nobj.parent_type and e.edge == nobj.type and e.expiry_minutes <> 0:
                                                nobj.expiry_time = (datetime.strptime(
                                                    nobj.download_time, DATE_FMT) + timedelta(minutes=e.expiry_minutes)).strftime(DATE_FMT)
                                                break

                              while page_status == 'OK' and (not os.path.isfile('stop')):
                                    si = json.dumps(obj, indent=1)
                                    s_ready = json.dumps(obj)
                                    nobj.response_size = nobj.response_size + len(s_ready)
                                    obj['fbi_id'] = nobj.id
                                    obj['fbi_object_reference'] = nobj.ref
                                    obj['fbi_level'] = nobj.level
                                    obj['fbi_fbo_type'] = nobj.fbo_type
                                    obj['fbi_object_type'] = nobj.type
                                    obj['fbi_page'] = nobj.page
                                    obj['fbi_parent_id'] = nobj.parent_id
                                    obj['fbi_parent_type'] = nobj.parent_type
                                    obj['fbi_root'] = nobj.root
                                    obj['fbi_root_type'] = nobj.root_type
                                    obj['fbi_download_time'] = str(
                                        nobj.download_time)
                                    obj['fbi_expiry_time'] = str(
                                        nobj.expiry_time)
                                    s_ready=json.dumps(obj)
                                    #send_file(filename, dir, text)
                                    #send_file(nvl(nobj.id, nobj.ref).replace(':','-') + postfix + '_' + nobj.download_time, str(nobj.type), s_ready)
                                    save_file(datetime.now().strftime("%Y%m%d%H") + "_" + str(os.getpid()), TEMP_DIR + str(nobj.type).replace(':','-').replace('/','_') + '/', s_ready + "\n")
				    #Save to separated folder if the request was processed by realtime worker process. 
				    #Interface must be defined for outside systems instead of the folder.
				    if rtflag == True:
					  save_file(nvl(nobj.id, nobj.ref).replace(':','-').replace('/','_') + postfix + '_' + nobj.download_time, LOCAL_RT_OUTPUT_DIR + str(nobj.type) + '/', s_ready + "\n")
                                    if nobj.root_type == 'page': #Different root type means different entry point and different traversal level
					  LEVEL = MTPAGE_LEVEL
                                    else:
					  LEVEL = SSOUSER_LEVEL #user level

				    if nobj.level < LEVEL:
                                          logging.debug(
                                              'worker(' + str(os.getpid()) + '): call add_connected_objs, object length: ' + str(len(si)))
                                          add_connected_objs(si, nobj, nq)
				    
				    #Put only edges into the queue when reaching the max of depth level. 
                                    if nobj.level < LEVEL + 1 and nobj.type <> 'unknown' and nobj.id <> 'unknown':
                                                add_connected_edges(nobj, nq)

                                    if SAVE_META:
                                          save_meta(obj, get_type(obj))
                                    try:
                                          obj = requests.get(
                                              obj['paging']['next']).json()
                                    except:
                                          break
                                    # No paging for followings:
                                    if nobj.type == 'insights' or nobj.type == 'unknown':
                                          break
                                    j = j + 1
                                    counter = counter + 1
                                    nobj.page = j
                                    postfix = '_' + str(j)
                                    s = json.dumps(obj)
                                    page_status = check_result(s)
                                    if chk_created_date(s,datetime.strptime(pdownload_time, DATE_FMT)) > 0.97:
                                          page_status = 'ALREADY_DOWNLOADED'
                              nq.put(nobj)
                              log(nobj)
                  #logging.info(
                  #    'worker(' + str(os.getpid()) + '): processed request: ' + str(i))
                  #print 'worker(' + str(os.getpid()) + '): processed request: ' + str(i)
                  i = i + 1
            m = datetime.now().minute
            # Count the request for every minute, if the minute changed store into
            # the list and reset the counter
            if m <> lm:
                  cntl.insert(0, counter)
                  logging.info(
                      "worker(" + str(os.getpid()) + "): requests processed from starting:  " + str(i))
                  logging.info(
                       "worker(" + str(os.getpid()) + "): requests processed in last minutes:  " + str(counter))
                  logging.info(
                      "worker(" + str(os.getpid()) + "): requests processed in last 10 minutes:  " + str(sm))
                  counter = 0
            lm = m
                  # If nothing to do, wait a second
            if sm >= MAX_WCALL or rq.empty():   #Main loop
                   time.sleep(1)
      logging.info('worker(' + str(os.getpid()) + '): STOPPED AND QUIT') #Main code
      return

#  MAIN PROGRAM BEGINS HERE
#
#

objects = []
edges = []
fields = []
load_meta() #To fill up objects, edges and fields lists
jobs = []

manager = multiprocessing.Manager()
requestq = manager.Queue()
resultq = manager.Queue()
rtrequestq = manager.Queue() #realtime queue

# Connection to HDFS Server: 10.35.178.195
if USE_HDFS:
	hdfs = KerberosClient(url= 'http://'+HDFS_HOST+':'+HDFS_PORT,root='/')

# Check if initialization is needed. Cleaning up folders.
if len(sys.argv) > 1 and sys.argv[1] == '-i':
      if os.path.isfile('fbi.db'):
            os.remove('fbi.db')
      if os.path.isfile('fbi.result.log'):
            os.remove('fbi.result.log')
      if os.path.isdir(LOCAL_OUTPUT_DIR):
            shutil.rmtree(LOCAL_OUTPUT_DIR)
      if os.path.isdir(LOCAL_SSO_STAGING_DIR):
            shutil.rmtree(LOCAL_SSO_STAGING_DIR)
      if os.path.isdir(LOCAL_SSO_ARCHIVE_DIR):
            shutil.rmtree(LOCAL_SSO_ARCHIVE_DIR)
      if os.path.isdir(TEMP_DIR):
            shutil.rmtree(TEMP_DIR)
      if os.path.isdir(LOCAL_RT_OUTPUT_DIR):
            shutil.rmtree(LOCAL_RT_OUTPUT_DIR)
      if os.path.isdir(LOCAL_RT_INPUT_DIR):
            shutil.rmtree(LOCAL_RT_INPUT_DIR)
      os.makedirs(LOCAL_RT_INPUT_DIR)
      os.makedirs(LOCAL_RT_INPUT_DIR+'archive')
      os.makedirs(LOCAL_SSO_STAGING_DIR)
      os.makedirs(LOCAL_SSO_ARCHIVE_DIR)
      if USE_HDFS:
            try:
		  hdfs.delete(REMOTE_OUTPUT_DIR, recursive=True)
            except:
                  pass
      # db = dataset.connect('mysql://root:@localhost/fbi')
      db = dataset.connect('sqlite:///fbi.db')
      table = db['request']
      # first object to download
      io = Request('TelekomHU', 0, 'page', '', '', 'TelekomHU', 'page', 1)
      backup_request(table, io)
      res = db.query('CREATE INDEX "IDX_FILTER" on request (status ASC)')
      res = db.query(
          'CREATE INDEX "IDX_SORT" on request (status ASC, level ASC, priority ASC)')
      res = db.query(
          'CREATE INDEX "IDX_SORT2" on request (status ASC, expiry_time ASC, level ASC, priority ASC)')
      res = db.query('CREATE INDEX "IDX_LOOKUP" on request (rid ASC)')

# Starting the uploader
up = multiprocessing.Process(target=uploader, args=())
up.start()

# Starting the queue manager
qm = multiprocessing.Process(target=qmanager, args=(resultq, requestq,))
qm.start()

# Starting the realtime queue manager
rqm = multiprocessing.Process(target=rtqmanager, args=(rtrequestq,))
rqm.start()

# Starting workers
for i in range(PARALLEL):
      if TOKEN_TYPE == 'GRAPHAPI-PARALLEL':
            tf = TOKEN_FILE + '.' + str(i/TOKEN_ALLOC+1)
      else:
            tf = TOKEN_FILE
      if i < RTW_PARALLEL:
            rtflag = True
            p = multiprocessing.Process(target=worker, args=(resultq, rtrequestq, rtflag, tf,))
            jobs.append(p)
            p.start()
      else:
            rtflag = False
            p = multiprocessing.Process(target=worker, args=(resultq, requestq, rtflag, tf,))
            jobs.append(p)
            p.start()

# Wait for worker exit
for i in jobs:
      i.join()

# Send stop to queue manager and wait for exit
#open('stop_qm', 'w').close()
rqm.join()
qm.join()
up.join()

#UPLOAD 
for dp, dn, filenames in os.walk(TEMP_DIR):
      for f in filenames:
            p = os.path.join(dp, f) 
            with open (p, "r") as mf:
                  if(send_file(f, dp.replace(TEMP_DIR,''), mf.read())):
                        os.remove(p)

if USE_HDFS and os.path.isfile(LOG_FILE):
      d = REMOTE_OUTPUT_DIR + '_fbi_log/'
      fn = d + LOG_FILE
      try:
	    hdfs.status(d)
      except:
	    hdfs.makedirs(d)
      with open(LOG_FILE) as file_data:
	    hdfs.write(fn, file_data, overwrite = True)

if os.path.isfile('stop'):
      os.remove('stop')

	  
