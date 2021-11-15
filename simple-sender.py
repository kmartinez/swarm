# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Copyright (C) 2021, Swarm Technologies, Inc.  All rights reserved.  #
# Simplified version without screen, wifi etc
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
VERSION = '1.0'
import board
import displayio
import digitalio
import terminalio
import busio
import time
import neopixel
from adafruit_display_text import label
import adafruit_displayio_sh1107
from barbudor_ina3221 import *
import supervisor
import sys
import microcontroller
import json
from binascii import hexlify
from microcontroller import watchdog as w
from watchdog import WatchDogMode
from adafruit_debouncer import Debouncer
import gc

ina3221 = None
tile = None
tileLine = bytearray(800)
tilePtr = 0

TILE_STATE_UNKNOWN = 0
TILE_STATE_REBOOTING = 1
TILE_STATE_2 = 2
TILE_STATE_3 = 3
TILE_STATE_4 = 4
TILE_STATE_5 = 5
TILE_STATE_CONFIGURED = 6

tileStateTable = [('$FV',   '$FV 20',              4, TILE_STATE_2, TILE_STATE_REBOOTING),  # 0 state
                  ('$RS',   '$TILE BOOT,RUNNING', 30, TILE_STATE_2, TILE_STATE_REBOOTING),  # 1 state
                  ('$DT 5', '$DT OK',              4, TILE_STATE_3, TILE_STATE_REBOOTING),  # 2 state
                  ('$GS 5', '$GS OK',              4, TILE_STATE_4, TILE_STATE_REBOOTING),  # 3 state
                  ('$GN 5', '$GN OK',              4, TILE_STATE_5, TILE_STATE_REBOOTING),  # 4 state
                  ('$RT 5', '$RT OK',              4, TILE_STATE_CONFIGURED, TILE_STATE_REBOOTING),  # 5 state
                  (None,     None,                 0, TILE_STATE_CONFIGURED, TILE_STATE_CONFIGURED)]  # 6 state
tileTimeout = 0.0
tileState = TILE_STATE_UNKNOWN

tcpLine = bytearray(800)
tcpPtr = 0
i2c = None

TCPHOST = ""
TCPPORT = 23
TIMEOUT = None
BACKLOG = 2
MAXBUF = 256
TCPSTATE_LISTENING = 1
TCPSTATE_CONNECTED = 2
TCPSTATE = TCPSTATE_LISTENING
tcplistener = None
tcpconn = None
pool = None

HTTPHOST = None
HTTPPORT = 80
web_app = None
wsgiServer = None


config = None
displayLines = []
inaChannel = 1
inaConnected = False
inaData = {1: (None, None), 2: (None, None), 3: (None, None)}

switchA = None
switchC = None

accumulate = ""
inaTime = 0

pixels = neopixel.NeoPixel(board.IO38, 2, bpp=4, pixel_order=neopixel.GRBW)

mdata = []
lastGN = None
lastDT = None
lastRSSI = None
nextGPSTime = 0
gpsCount = 0

def makeTileCmd(cmd):
  cbytes = cmd.encode()
  cs = 0
  for c in cbytes[1:]:
    cs = cs ^ c
  return cbytes + b'*%02X\n'%cs


def tileCheck(line):
  global tileTimeout
  if  tileStateTable[tileState][1] in line:
    tileTimeout = -1.0


def tileStart():
  global tileState, tileTimeout

  tileState = TILE_STATE_UNKNOWN
  while tileState != TILE_STATE_CONFIGURED:
    tile.write(b'\n' + makeTileCmd(tileStateTable[tileState][0]))
    tileTimeout = time.monotonic() + tileStateTable[tileState][2]
    while (tileTimeout > 0.0) and (tileTimeout > time.monotonic()):
      tilePoll()
      serialPoll()
      w.feed()
    if tileTimeout  < 0.0:
      tileState = tileStateTable[tileState][3]
    else:
      tileState = tileStateTable[tileState][4]


def tileInit():
  global tile
  tile = busio.UART(board.TX,board.RX,baudrate=115200,receiver_buffer_size=8192,timeout=0.0)
  tileStart()


def tileParseLine(line):
  global lastDT, lastGN, lastRSSI
  if len(line) < 4:
    return
  if line[len(line) - 3] != '*':
    return
  cksum1 = 0
  cksum2 = int(line[-2:], 16)
  for c in line[1:-3]:
    cksum1 = cksum1 ^ ord(c)
  if cksum1 != cksum2:
    return
  if tileState != TILE_STATE_CONFIGURED:
    tileCheck(line)
    return
  if line[0:3] is "$TD":
    if len(mdata) > 10:
      mdata.pop(0)
    mdata.append(line)
  if line[0:3] is "$DT":
    lastDT = line
  if line[0:3] is "$GN":
    lastGN = line
  parse = line[:-3].split(' ')
  if parse[0] == '$RT':
    if 'RSSI' in parse[1]:
      if ',' in parse[1]:
        rdata = line[4:-3].split(',')
        rtdata = []
        for r in rdata:
          rtdata.append(r.split('='))
        rtdata = dict(rtdata)
        d, t = rtdata['TS'].split(' ')
        d = d.split('-')
        t = t.split(':')
        dtString = d[0][2:]+d[1]+d[2]+'T'+t[0]+t[1]+t[2]
        print(rtdata)

        print('R:' + rtdata['RSSI'] + ' S:' + rtdata['SNR'] + ' F:' + rtdata['FDEV'])
      else:
        rssi = parse[1].split('=')
        print("RSSI: " + rssi[1])
        irssi = int(rssi[1])
        lastRSSI = irssi
        if config['wifi'] == 'enabled':
          if irssi > -91:
            pixels[0] = (16, 0, 0, 0)
          elif irssi < -95:
            pixels[0] = (0, 16, 0, 0)
          else:
            pixels[0] = (16, 16, 0, 0)
          pixels.write()


def tilePoll():
  global tilePtr
  chars = tile.read(20)
  if chars == None:
    return
  if tcpconn != None:
    try:
      x = tcpconn.send(chars)
    except:
      pass


  for c in chars:
    if c == 0x0A:
      tileParseLine(tileLine[:tilePtr].decode())
      tilePtr = 0
    elif c == 0x08 and tilePtr != 0:
      tilePtr = tilePtr - 1
    elif c >= 0x20 and c <= 0x7f and tilePtr < len(tileLine):
      tileLine[tilePtr] = c
      tilePtr = tilePtr + 1
  pass


def inaInit():
  global ina3221, inaConnected
  try:
    ina3221 = INA3221(i2c, shunt_resistor = (0.01, 0.01, 0.01))
    ina3221.update(reg=C_REG_CONFIG, mask=C_AVERAGING_MASK | C_VBUS_CONV_TIME_MASK | C_SHUNT_CONV_TIME_MASK | C_MODE_MASK,
                                     value=C_AVERAGING_128_SAMPLES | C_VBUS_CONV_TIME_8MS | C_SHUNT_CONV_TIME_8MS | C_MODE_SHUNT_AND_BUS_CONTINOUS)
    ina3221.enable_channel(1)
    ina3221.enable_channel(2)
    ina3221.enable_channel(3)
    inaConnected = True
  except:
    print("ina disconnected")
    inaConnected = False


def inaPoll():
  global inaChannel, inaTime, inaConnected, inaData
  if not inaConnected:
    inaInit()
    return
  if time.time() - inaTime > 5:
    try:
      inaChans = {1:'BAT:', 2:'SOL:', 3:'3V3:'}
      bus_voltage = ina3221.bus_voltage(inaChannel)
      current = ina3221.current(inaChannel)

      print("%s %6.3fV %6.3fA"%(inaChans[inaChannel], bus_voltage, current))
      inaData[inaChannel] = (bus_voltage, current)
      inaChannel = inaChannel + 1
      if inaChannel == 4:
        inaChannel = 1
    except:
      inaConnected = False
    inaTime = time.time()



def serialInit():
  print("", end='')


def serialPoll():
  global accumulate
  if supervisor.runtime.serial_bytes_available:
    accumulate += sys.stdin.read(1)
  if "\n" in accumulate:
    accumulate = accumulate[:-1]
    params = accumulate.split(' ')
    if params[0] == '@reset':
      print("Resetting...")
      microcontroller.reset()
    elif params[0] == '@color':
      if len(params) ==  5:
        if config['wifi'] == 'enabled':
          pixels[1] = (int(params[1]),int(params[2]),int(params[3]),int(params[4]))
          pixels.write()
    elif params[0] == '@set':
      if params[1] == 'mode':
        if params[2] in ['ap', 'sta']:
          config['mode'] = params[2]
          print(f"Successfully set mode to {params[2]}.")
          writePreferences()
      if params[1] == 'wifi':
        if params[2] in ['enabled', 'disabled']:
          config['wifi'] = params[2]
          if config['wifi'] == 'disabled':
            pixels[0] = (0,0,0,0)
            pixels[1] = (0,0,0,0)
            pixels.write()
          print(f"Successfully {params[2]} wifi.")
          writePreferences()
          print("Resetting...")
          microcontroller.reset()
      if params[1] == 'ssid':
        config['ssid'] = accumulate[10:].strip()
        print(f"Successfully set ssid to {config['ssid']}.")
        writePreferences()
      if params[1] == 'pw':
        config['password'] = accumulate[8:].strip()
        print(f"Successfully set password to {config['password']}.")
        writePreferences()
      if params[1] == 'interval':
        if int(params[2]) == 0 or (int(params[2]) >= 15 and int(params[2]) <= 720):
          if int(params[2]) == 0 and config['interval'] > 0:
            config['interval'] = config['interval'] * -1
            print(f"Successfully set interval to off.")
          else:
            config['interval'] = int(params[2])
            print(f"Successfully set interval to {config['interval']}.")
          gpsInit()
          writePreferences()
        else:
          print("Interval can only be 0 or 15-720 minutes.")
    elif params[0] == '@show':
      if len(params) == 2:
        if params[1] == 'battery':
          print('BAT: ' + str(inaData[1][0]) + 'V ' + str(inaData[1][1]) + 'A')
        if params[1] == '3v3':
          print('3V3: ' + str(inaData[3][0]) + 'V ' + str(inaData[3][1]) + 'A')
        if params[1] == 'solar':
          print('SOL: ' + str(inaData[2][0]) + 'V ' + str(inaData[2][1]) + 'A')
      else:
        print('wifi mode:', config['mode'])
        print('wifi:', config['wifi'])
        print('wifi ssid:', config['ssid'])
        print('wifi pw:  ', config['password'])
        print('gps interval: ' + (str(config['interval']), 'OFF')[config['interval'] <= 0] + '\n')
    elif params[0] == '@factory':
      microcontroller.nvm[0] = 0
      print("Cleared NVM and Resetting...")
      microcontroller.reset()
    elif params[0] == '@test':
      tileParseLine(' '.join(params[1:]))
    elif params[0] == '@help':
      print(helpMessage)
    else:
      print("Invalid command. Type @help for help.")
    print("", end='')
    accumulate = ""


def urlDecode(s):
  i = 0
  r = ''
  while i < len(s):
    if s[i] == '+':
      r = r + ' '
    elif s[i] == '%':
      r = r + chr(int(s[i+1:i+3], 16))
      i = i + 2
    else:
      r = r + s[i]
    i = i + 1
  return r


def gpsInit():
  print('GPS Ping: ' + (str(config['interval']) + 'min', 'OFF')[config['interval'] <= 0])


def gpspoll():
  global nextGPSTime,gpsCount
  if config['interval'] > 0:
    if time.time() > nextGPSTime and lastGN is not None and lastDT is not None:
      gpsObj = {}
      gn = lastGN[4:-3].split(',')
      s = lastDT
      gpsObj['d'] = 946684800 + time.mktime((int(s[4:8]), int(s[8:10]), int(s[10:12]), int(s[12:14]), int(s[14:16]), int(s[16:18]), -1, -1, -1))
      gpsObj['lt'] = float(gn[0])
      gpsObj['ln'] = float(gn[1])
      gpsObj['a'] = float(gn[2])
      gpsObj['c'] = float(gn[3])
      gpsObj['s'] = float(gn[4])
      gpsObj['n'] = gpsCount
      gpsObj['si'] = inaData[2][1]
      gpsObj['sv'] = inaData[2][0]
      gpsObj['bi'] = inaData[1][1]
      gpsObj['bv'] = inaData[1][0]
      gpsObj['ti'] = inaData[3][1]
      gpsObj['r'] = lastRSSI
      gpsCount += 1
      s = json.dumps(gpsObj)
      s = s.replace(' ', '')
      h = b'$TD AI=65535,' + hexlify(s.encode())
      cs = 0
      for c in h[1:]:
        cs = cs ^ c
      h = h + b'*%02X\n'%cs
      tile.write(h)
      nextGPSTime = config['interval'] * 60 + time.time()


def writePreferences():
  configString = json.dumps(config)
  ba = bytearray(configString, 'utf-8')
  microcontroller.nvm[0:len(ba)] = ba
  microcontroller.nvm[len(ba)] = 0


def readPreferences():
  global config
  try:
    x = microcontroller.nvm[0]
  except:
    microcontroller.nvm[0] = 0
  i = 0
  configString = ""
  while microcontroller.nvm[i] is not 0:
    configString += chr(microcontroller.nvm[i])
    i = i + 1
  if configString == "":
    configString = "{}"
  config = json.loads(configString)
  if not 'mode' in config:
    config['mode'] = 'ap'
  if not 'ssid' in config:
    config['ssid'] = 'swarm'
  if not 'password' in config:
    config['password'] = '12345678'
  if not 'interval' in config:
    config['interval'] = 60
  if not 'wifi' in config:
    config['wifi'] = "enabled"


def watchDogInit():
  w.timeout = 60
  w.mode = WatchDogMode.RESET
  w.feed()


def buttonInit():
  global switchA, switchC

  pinA = digitalio.DigitalInOut(board.D5)
  pinA.direction = digitalio.Direction.INPUT
  pinA.pull = digitalio.Pull.UP
  switchA = Debouncer(pinA)

  pinC = digitalio.DigitalInOut(board.D20)
  pinC.direction = digitalio.Direction.INPUT
  pinC.pull = digitalio.Pull.UP
  switchC = Debouncer(pinC)



def buttonPoll():
  switchA.update()
  if switchA.rose: # just released
    if config['wifi'] == "enabled":
      config['wifi'] = "disabled"
      pixels[0] = (0,0,0,0)
      pixels[1] = (0,0,0,0)
      pixels.write()
    else:
      config['wifi'] = "enabled"
    writePreferences()
    print(f"Successfully {config['wifi']} wifi.")
    print("Resetting...")
    microcontroller.reset()

  switchC.update()
  if switchC.rose:
    config['interval'] = config['interval'] * -1
    writePreferences()
    gpsInit()


def factoryResetCheck():
  switchA.update()
  if not switchA.value:
    microcontroller.nvm[0] = 0
    while not switchA.value:
      switchA.update()
    print("Cleared NVM and Resetting...")
    microcontroller.reset()

print("watchdog init")
watchDogInit()
print("button init")
buttonInit()
factoryResetCheck()
i2c = busio.I2C(board.SCL, board.SDA, frequency=400000)
print("reading prefs")
readPreferences()
print("ina init")
inaInit()
#serialInit()
print("tile init")
tileInit()
print("gps init")
gpsInit()
print("starting loop")
while True:
  tilePoll()
  inaPoll()
  gpspoll()
  serialPoll()
  buttonPoll()
  w.feed()
  gc.collect()



