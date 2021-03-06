#!/usr/bin/env python3
# -.- coding: utf-8 -.-
try:
    import subprocess
    import os
    import sys
    import time
    import json
    import pyshark
    import sqlite3
    import datetime
    import argparse
    import threading
    import traceback
    import concurrent.futures
except KeyboardInterrupt:
    debug("\n[I] Stopping...")
    raise SystemExit
except:
    debug("[!] Failed to import the dependencies... " +\
            "Please make sure to install all of the requirements " +\
            "and try again.")
    raise SystemExit

parser = argparse.ArgumentParser(usage="packetSniffer.py [options]")
parser.add_argument("--debug", action="store_true", help="turn debug mode on")

args = parser.parse_args()
debugMode = args.debug
alreadyStopping = False

externalOptionsSet = False
if debugMode:
    externalOptionsSet = True
    print("[I] Showing Debug Messages...")
if externalOptionsSet:
    print()

def debug(msg=""):
    if debugMode:
        print("[DEBUG] " + msg)

debug("Welcome to Nighttime Sniffer")

debug("[I] Selecting correct interface")
try:
    wirelessInterfaces = subprocess.check_output(["lshw","-C","network"],shell=True)
    wirelessInterfaces = str(wirelessInterfaces).split("*")
    wirelessInterfaces = [x for x in wirelessInterfaces if "Ralink" in x][0].split("\\n")
    interfaceName = [x for x in wirelessInterfaces if "logical name" in x][0].split(":")[1].strip()
    if "mon" not in interfaceName:
        subprocess.call("airmon-ng start " + interfaceName, shell=True)
        interfaceName += "mon"
except:
    debug("[I] Error setting up interface. Are you sure adapter is plugged in?")
    sys.exit(1)

debug("[I] Grabbing Customer Data From Server")
try:
    #TODO
    #Grab from server
    #Write to serverInfo.json
    #Check documentation for specific way to write data
    str = 1 + "hello" #Causes try block to fail and except loop to run
except:
    debug("[I] Server information not read")
    serverFile = open("serverInfo.json","r")
    serverInfo = json.load(serverFile)
    serverFile.close()

debug("[I] Loading OUI Database...")
try:
    ouiFile = open("oui.json", "r")
    ouiObj = json.load(ouiFile)
    ouiFile.close()
except:
    debug("[I] Couldn't resolve OUI database")
    ouiObj = {}

debug("[I] Logging Current Time")
currentTime = datetime.datetime.now()

debug("[I] Setting Wake Time")
wakeHour = (int(serverInfo["sleepTime"].split(":")[0]) + 1 + serverInfo["tzOffset"]) % 24
wakeMinute = serverInfo["sleepTime"].split(":")[1]
debug(str(wakeHour)+" " + wakeMinute)

debug("[I] Updating Cron Job")
try:
    subprocess.call("rm /etc/cron.d/digitalB_nighttime",shell=True)
except:
    debug("[I] Couldn't call processes to remove cronjob")
subprocess.call("touch /etc/cron.d/digitalB_nighttime",shell=True)
nighttimeJob = open("/etc/cron.d/digitalB_nighttime","w")
nighttimeCommand = "{} {} * * * root cd /root/DigitalB_Sniffer && /usr/bin/python3 nighttimeSniffer.py".format(wakeMinute, wakeHour)
nighttimeJob.write(nighttimeCommand)
nighttimeJob.close()

debug("[I] Setting Sleep Time")
sleepDate = datetime.date.today() + datetime.timedelta(days = 1)
sleepHour = (int(serverInfo["wakeTime"].split(":")[0]) - 1 + serverInfo["tzOffset"]) % 24
sleepMin = int(serverInfo["wakeTime"].split(":")[1])
sleepTime = datetime.time(hour=sleepHour,minute=sleepMin,second=0)
sleepTime = datetime.datetime.combine(sleepDate,sleepTime)

debug("[I] Initiliazing Dictionary")
deviceDictionary = {}

def stop():
    global alreadyStopping
    debug("stoping called")
    if not alreadyStopping:
        debug("setting stopping to true")
        alreadyStopping = True
        debug("\n[I] Stopping...")
        debug("[I] Saving results to overnight_capture.db")
        saveToMySQL()
        debug("[I] Results saved to overnight_capture.db")

        debug("[I] Trying to read from capture_devices.json")
        try:
            file = open("constant_devices.json", "r")
            constant_devices = json.load(file)
            file.close()
        except:
            constant_devices = []

        debug("[I] Updating list of constant_devices")
        db = sqlite3.connect("overnight_capture.db")
        cur = db.cursor()
        cur.execute("SELECT * FROM packetSniffer")
        rows = cur.fetchall()
        for row in rows:
            if row[3] != 1:
                startTime = datetime.datetime.strptime(row[5],"%Y-%m-%d %H:%M:%S")
                stopTime = datetime.datetime.strptime(row[4], "%Y-%m-%d %H:%M:%S")
                if ((stopTime - startTime).total_seconds() / 3600) > 6:
                    if str(row[0]) not in constant_devices:
                        constant_devices.append(str(row[0]))

        file = open("constant_devices.json","w")
        file.write(json.dumps(constant_devices))
        file.close()
        subprocess.call("rm overnight_capture.db", shell = True)
        debug("Stopped at: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        debug("[I] packetSniffer stopped.")
        raise SystemExit

def channelHopper():
    while True:
        if not alreadyStopping:
            channels = [1, 6, 11]
            for channel in channels:
                subprocess.call("iwconfig " + interfaceName + " channel " +
                           str(channel) + " > /dev/null 2>&1", shell=True)
                debug("[CHOPPER] HI IM RUNNING THIS COMMAND: " +
                      "iwconfig " + interfaceName + " channel " + str(channel))
                debug("[CHOPPER] HI I CHANGED CHANNEL TO " + str(channel))
                time.sleep(5)
        else:
            debug("[CHOPPER] IM STOPPING TOO")
            sys.exit()

def deviceUpdater():
    while True:
        if not alreadyStopping:
            debug("[I] " + str(len(deviceDictionary))+ " devices found")
            cpuTemp = subprocess.check_output(["cat", "/sys/class/thermal/thermal_zone0/temp"])
            cpuTemp = int(cpuTemp) / 1000
            debug("[I] Cpu Temp: " + str(cpuTemp))
            debug("[I] Time: " + str(currentTime))
            saveToMySQL()
            time.sleep(900)
        else:
            debug("[deviceUpdate] IM STOPPING TOO")
            sys.exit()

def resolveMac(mac):
    global ouiObj
    if mac[:8].upper() in ouiObj:
        return ouiObj[mac[:8].upper()]
    return "COULDNT-RESOLVE"

def packetHandler(pkt):
    try:
        global currentTime
        global deviceDictionary

        rssi = pkt.radiotap.dbm_antsignal
        mac_address = pkt.wlan.ta

        vendor = resolveMac(mac_address)

        currentTime = datetime.datetime.now()

        if mac_address in deviceDictionary:
            deviceDictionary[mac_address]["timeLastSeen"] = currentTime.strftime("%Y-%m-%d %H:%M:%S")
            deviceDictionary[mac_address]["timesCounted"] += 1
            if rssi < deviceDictionary[mac_address]["RSSI"]:
                deviceDictionary[mac_address]["RSSI"] = rssi
        else:
            deviceDictionary[mac_address] = {"RSSI":rssi, "Vendor":vendor,
                                   "timesCounted":1, "timeFirstSeen": currentTime.strftime("%Y-%m-%d %H:%M:%S"),
                                   "timeLastSeen":"N/A"}
    except KeyboardInterrupt:
        stop()
    except:
        debug("[!!!] CRASH IN packetHandler")
        debug(traceback.format_exc())

def saveToMySQL():
    try:
        global deviceDictionary
        debug("saveToMySQL called")
        db = sqlite3.connect("overnight_capture.db")
        cursor = db.cursor()
        for m in deviceDictionary:
            r = deviceDictionary[m]["RSSI"]
            v = deviceDictionary[m]["Vendor"]
            tc = deviceDictionary[m]["timesCounted"]
            tfs = deviceDictionary[m]["timeFirstSeen"]
            tls = deviceDictionary[m]["timeLastSeen"]
            cursor.execute("INSERT OR REPLACE INTO packetSniffer (mac_address, vendor, rssi, timesCounted, timeFirstSeen, timeLastSeen) VALUES (?,?,?,?,?,?)", (m,v,r,tc,tfs,tls))
        db.commit()
        db.close()
    except:
        debug("Crash saveSQL")
        debug("[!!!] CRASH IN saveToMySQL")
        debug(traceback.format_exc())

def main():
    global alreadyStopping

    debug("[I] Setting up SQLite...")
    try:
        setupDB = sqlite3.connect("overnight_capture.db")
    except:
        debug("\n[!] Cant connect to database. Permission error?\n")
        exit()
    setupCursor = setupDB.cursor()
    setupCursor.execute("DROP TABLE IF EXISTS packetSniffer")
    setupCursor.execute(
        """CREATE TABLE packetSniffer
            (mac_address VARCHAR(50) primary key, vendor VARCHAR(50),
             rssi INT, timesCounted INT, timeFirstSeen VARCHAR(50),
             timeLastSeen VARCHAR(50))""")
    setupDB.commit()
    setupDB.close()

    debug("[I] Starting channelhopper in a new thread...")
    path = os.path.realpath(__file__)
    chopper = threading.Thread(target=channelHopper)
    chopper.daemon = True
    chopper.start()

    debug("[I] Starting deviceUpdater in a new thread...")
    path = os.path.realpath(__file__)
    updater = threading.Thread(target=deviceUpdater)
    updater.daemon = True
    updater.start()

    debug("\n[I] Sniffing started... Please wait for requests to show up...\n")

    while True:
        try:
            timeoutPeriod = (sleepTime - currentTime).total_seconds()
            capture = pyshark.LiveCapture(interface=interfaceName, bpf_filter="type mgt subtype probe-req")
            capture.apply_on_packets(packetHandler, timeout = timeoutPeriod)
        except KeyboardInterrupt:
            stop()
        except concurrent.futures.TimeoutError:
            stop()
        except:
            debug("[!] An error occurred. Debug:")
            debug(traceback.format_exc())
            debug("[!] Restarting in 5 sec... Press CTRL + C to stop.")
            try:
                time.sleep(5)
            except:
                stop()




if __name__ == "__main__":
    main()
