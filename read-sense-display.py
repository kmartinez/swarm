import board
import time
import busio
import adafruit_mcp9808
import adafruit_sgp30
from adafruit_bme280 import basic as adafruit_bme280
import displayio
import terminalio
from adafruit_display_text import label
import adafruit_displayio_sh1107
WIDTH = 128
HEIGHT = 64
BORDER = 0
displayio.release_displays()
i2c = board.I2C()
display_bus = displayio.I2CDisplay(i2c, device_address=0x3C)
display = adafruit_displayio_sh1107.SH1107(display_bus, width=WIDTH, height=HEIGHT)

splash = displayio.Group()
display.show(splash)
color_bitmap = displayio.Bitmap(WIDTH, HEIGHT, 1)
color_palette = displayio.Palette(1)
color_palette[0] = 0xFFFFFF  # White

def printl(tl, line):
    text_area = label.Label(terminalio.FONT, text=tl, color=0xFFFFFF, x=8, y=line)
    splash.append(text_area)
    display.show(splash)

# Create sensor object, using the board's default I2C bus.
i2c = board.I2C()   # uses board.SCL and board.SDA
bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c)
sgp30 = adafruit_sgp30.Adafruit_SGP30(i2c)
# change this to match the location's pressure (hPa) at sea level
bme280.sea_level_pressure = 1028.0
#mcp = adafruit_mcp9808.MCP9808(i2c)

sgp30.iaq_init()
sgp30.set_iaq_baseline(0x8973, 0x8AAE)


while True:
#    print("Temperature +-0.25: {} C  ".format(mcp.temperature))
    temp = bme280.temperature
    co2 = sgp30.eCO2
    tvoc = sgp30.TVOC
    hum = bme280.relative_humidity
    print("Temperature: %0.1f C" % temp)
    printl(str(temp) + " C " + str(hum) + "%",10)
    print("Humidity: %0.1f %%" % hum)
    print("Pressure: %0.1f hPa" % bme280.pressure)
    print("Altitude = %0.2f m" % bme280.altitude)
    printl(str(co2) + " ppm CO2 ",20)
    printl(str(tvoc) + " ppb TVOC",30)
    print("eCO2 = %d ppm \t TVOC = %d ppb" % (co2,tvoc ))
    time.sleep(2)
