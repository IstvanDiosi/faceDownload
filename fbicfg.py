# 
# Script to set up initial parameters and environment configuration
# This script included in fbi.py as module
#
# Project: MT Social BI/SMCC pilot
# 201501212
# fbi.cfg.py
#
#
import datetime
from datetime import datetime, timedelta
import logging
import requests
# Get Facebook Access Token from https://developers.facebook.com/tools/explorer/ and save into fbi.access_token
TOKEN_TYPE = 'FBAPP'                      # Value list: FBAPP, GRAPHAPI-PARALLEL, GRAPHAPI
BATCH_DESC = 'SMCCPROBA'                # description of loading batch

# TSM Pilot environment
SSO_APP_ID = '814940338526409'          #SMCC pilot app  - facebook app id of SSO application. It is necessary to request long live user access token for SSO app
SSO_SECRET_KEY = 'd95caa2a458c703dad8be5891e82d46c'   #SMCC pilot app  - facebook key of SSO application. It is necessary to request long live user access token for SSO app
REMOTE_OUTPUT_DIR = 'user/hdfs/facebook/' + BATCH_DESC + '/'
REMOTE_SSO_INPUT_DIR = 'user/hdfs/sso/'    # User IDs of the entered SSO users
HDFS_HOST = '10.1.1.5'
HDFS_USER = 'hdfs'

# MT Production environment
#SSO_APP_ID = '808873495835143'		#TelekomFiok app - facebook app id of SSO application. It is necessary to request long live user access token for SSO app
#SSO_SECRET_KEY = '4fa0412c5b98da9e14034af6436db7a2'   #TelekomFiok app - facebook key of SSO application. It is necessary to request long live user access token for SSO app
#REMOTE_OUTPUT_DIR = 'user/facebook/json_folder/' + BATCH_DESC + '/'
#REMOTE_SSO_INPUT_DIR = 'user/facebook/sso_list/'    # User IDs of the entered SSO users
#HDFS_HOST = '172.28.164.4'
#HDFS_USER = 'facebook'


USE_HDFS = True    	    # True: save received json objects (response of facebook graph api) to the remote HDFS file system.
HDFS_PORT = '50070'         # WebHDFS port on HDFS_HOST
MTPAGE_LEVEL = 1            # Maximum level of depth of exploring the graph beginning from the MT FB page
SSOUSER_LEVEL = 1           # Maximum level of depth of exploring the graph beginning from an SSO user
PARALLEL = 12               # Number of worker processes
RTW_PARALLEL = 1            # Number of worker processes which serve realtime request (must be less or eqv. with PARALLEL)
TOKEN_ALLOC = 2             # Number of worker processes using the same access token in case of  'GRAPHAPI-PARALLEL' mode. Otherwise is not used.
MAX_CALL = 42000             # Maximum number of sent http requests to facebook in the last 10 minutes.
FB_REQ_RATE = 200	    # Maximum number of hourly request per user to Facebook server (Limitation policy 200 request/user/hour)
MAX_CALL60_LIMIT = 50*FB_REQ_RATE  
			    # Maximum number of sent http requests to facebook in the last 60 minutes. (fb user * 200) Force calculagted rate limit.
MIN_CALL60_LIMIT = 30*FB_REQ_RATE  
			    # Minimum number of sent http requests to facebook in the last 60 minutes. Force calculated rate limit.
MAX_WCALL = 300             # Maximum number of sent http requests per workers to facebook in the last 10 minutes.
MAX_RQSIZE = 250            # Maximum number of the reuqest in the reuqestq, after reaching the limit no new request will be added to requestq
INC_RQSIZE = 50             # Number of request added to requestq in one cycle
DEF_PRIORITY = 10000        # Default priority for the requests (if not defined)
OBJ_PRIORITY = 99           # Priority for the request in case of the lement is a new facbook object id (We do not know the type of the object)   
DATE_FMT = '%Y%m%d%H%M%S'   # dfault date format in this application
INF_DATETIME = datetime(9999,1,1) # INFINITY DATETIME
MIN_DATETIME = datetime(2015,1,1) # MINIMUM DATETIME     
MIN_BULKSIZE = 100          # Minimum number of records to insert into the database at one time
MAX_BULKSIZE = 1000         # Maximum number of records to insert into the database at one time
LOG_FILE = 'fbi.result.log'
TOKEN_FILE = 'fbi.access_token'
SAVE_LOCAL = True    # True: save received json objects (response of facebook graph api) to the local file system.
SAVE_META = False    # True: extract and save metadata information from received json files. (Useful for parametization)

LOCAL_OUTPUT_DIR = 'fbi_data/'
LOCAL_RT_OUTPUT_DIR = 'fbi_rtout/'
LOCAL_RT_INPUT_DIR = 'fbi_rtin/'
LOCAL_SSO_STAGING_DIR = 'fb_sso_stage/'  
LOCAL_SSO_ARCHIVE_DIR = 'fb_sso_arch/'
SSO_RETENTION_DAYS = 180                   # Retention time of SSO datas in days
TEMP_DIR = 'fbi_stage/'

START_TIME = datetime.now().strftime('%Y%m%d%H%M%S')
#LOG_FILE = LOG_FILE + '.'  + BATCH_DESC + '_' + START_TIME

requests.packages.urllib3.disable_warnings() #Due to configure kerberos has not been done in TSM platform. Every URL requests logging the following message InsecurePlatformWarning: A true SSLContext object is not available message.
logging.basicConfig(filename='fbi.log',format='%(asctime)s %(levelname)s %(message)s', level=logging.DEBUG)

