# dti_reader
Command-line tool to read the Shahe Dial Test Indicator / Dial Indicator / Raster Digital Indicator. 

## HW needed
The device comes with a usb-c to 9-pin cable. The device has a female 9-pin connector, your adapter will need to have a male connector.

## Use
Find the serial tty to use. The name depends on the os and the adapter. On macos it is something like `/dev/tty.usbserial-FTFCSM3B`. A sample command:
```
 % ./dti_reader.py --device /dev/tty.usbserial-FTFCSM3B --interval 0.3  --json
{"displacement": -4.531, "unit": "mm"}
{"displacement": -4.531, "unit": "mm"}
{"displacement": -4.531, "unit": "mm"}
```

 
