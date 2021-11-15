#!/usr/bin/python
# -*- coding: utf-8 -*-
# get data and append to a file
from pprint import pprint
import base64
import json
import requests

from swarmID import secrets
datafile = "datafile"
logfile = "logfile"
# define output of the REST request as json
# and other parameterized values used below
loginHeaders = {'Content-Type': 'application/x-www-form-urlencoded'}
hdrs = {'Accept': 'application/json'}
loginParams = {'username': secrets["username"], 'password': secrets["password"]}

hiveBaseURL = 'https://bumblebee.hive.swarm.space/hive'
loginURL = hiveBaseURL + '/login'
getMessageURL = hiveBaseURL + '/api/v1/messages'
ackMessageURL = hiveBaseURL + '/api/v1/messages/rxack/{}'

# dont do the ACK
doACK = False

# create a session
with requests.Session() as s:
    # log in to get the JSESSIONID cookie
    res = s.post(loginURL, data=loginParams, headers=loginHeaders)
    #print(res.url)

if res.status_code != 200:
    print("Invalid username or password; please use a valid username and passwor
d in loginParams.")
    exit(1)

# print out the JSESSIONID cookie
#print(s.cookies)

# let the session manage the cookie and get the output for the given appID
# only pull the last 10 items that have not been ACK'd
res = s.get(getMessageURL, headers=hdrs, params={'count': 10, 'status': 0})
# print(res)

messages = res.json()

# print out the prettied version of the JSON records for unacknowledge data reco
rds in the hive
print("jason dumps")
print(json.dumps(messages, indent=4))
f = open(logfile, "a")
f.write(json.dumps(messages, indent=4))
f.close()
