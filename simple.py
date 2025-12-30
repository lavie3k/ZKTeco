#!/usr/bin/env python2
# # -*- coding: utf-8 -*-
import sys
import traceback
import argparse
import time
import datetime
import json
import csv
import os
from builtins import input

sys.path.append("zk")

from zk import ZK, const
from zk.user import User
from zk.finger import Finger
from zk.attendance import Attendance
from zk.exception import ZKErrorResponse, ZKNetworkError

class BasicException(Exception):
    pass

conn = None
results = []

DEVICE_INFO_FIELDS = [
    'SDK build=1',
    'ExtendFmt',
    'UsrExtFmt',
    'Face FunOn',
    'Face Version',
    'Finger Version',
    'Old FW Compat',
    'IP Address',
    'Subnet Mask',
    'Gateway',
    'Device Time',
    'Firmware Version',
    'Platform',
    'Device Name',
    'Pin Width',
    'Serial Number',
    'MAC',
]

def styled_title(label):
    """Return a normalized, emphasized section title."""
    clean = str(label).strip('- ').upper()
    return '** {} **'.format(clean)

def status_marker(status):
    """Map result status to a visual marker."""
    normalized = str(status).upper()
    return {
        'OK': '[+]',
        'WARN': '[!]',
        'FAIL': '[x]',
        'INFO': '[i]',
    }.get(normalized, '[?]')

def announce_section(title):
    """Print a visually highlighted section title."""
    print('')
    print(styled_title(title))

def add_result(step, status, details):
    """Store a structured result row for later display."""
    results.append((step, str(status).upper(), str(details)))

def render_table(title, headers, rows):
    """Render text table with aligned columns."""
    if not rows:
        print('')
        print('{}: no data'.format(title))
        return
    str_rows = [tuple(str(value) for value in row) for row in rows]
    widths = [len(col) for col in headers]
    for row in str_rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt_row(values):
        return ' | '.join(val.ljust(width) for val, width in zip(values, widths))

    separator = '-+-'.join('-' * width for width in widths)
    print('')
    print(styled_title(title))
    print(fmt_row(headers))
    print(separator)
    for row in str_rows:
        print(fmt_row(row))
    print(separator)

def render_keyvalue_table(title, pairs):
    """Render key/value data using the shared table output."""
    render_table(title, ('Property', 'Value'), pairs)

def render_execution_results(title, rows):
    """Render execution results with status markers."""
    decorated = []
    for step, status, details in rows:
        decorated.append((status_marker(status), step, status, details))
    render_table(title, ('State', 'Step', 'Status', 'Details'), decorated)

def render_sizes_table(connection, title):
    """Read device sizes and present them in a table format."""
    connection.read_sizes()
    summary = str(connection).splitlines()
    rows = []
    for line in summary:
        clean = line.strip()
        if not clean:
            continue
        if ':' in clean:
            key, value = clean.split(':', 1)
            rows.append((key.strip(), value.strip()))
        else:
            rows.append((clean, ''))
    render_keyvalue_table(title, rows)

def collect_user_rows(users, target_uid=None):
    """Prepare user information rows and find a matching user if requested."""
    rows = []
    prev = None
    for user in users:
        privilege = 'User' if user.privilege == const.USER_DEFAULT else 'Admin-%s' % user.privilege
        rows.append((
            user.uid,
            user.name,
            privilege,
            user.group_id,
            user.user_id,
            user.password,
            user.card
        ))
        if target_uid and user.uid == target_uid:
            prev = user
    return rows, prev

def device_info_rows(info_map):
    """Order device information for display/export."""
    return [(field, info_map.get(field, '')) for field in DEVICE_INFO_FIELDS]

def build_device_info(conn, sdk_build=None):
    """Collect device metadata from an active connection."""
    info = {}
    info['SDK build=1'] = sdk_build if sdk_build is not None else conn.set_sdk_build_1()
    info['ExtendFmt'] = conn.get_extend_fmt()
    info['UsrExtFmt'] = conn.get_user_extend_fmt()
    info['Face FunOn'] = conn.get_face_fun_on()
    info['Face Version'] = conn.get_face_version()
    info['Finger Version'] = conn.get_fp_version()
    info['Old FW Compat'] = conn.get_compat_old_firmware()
    net = conn.get_network_params()
    info['IP Address'] = net.get('ip')
    info['Subnet Mask'] = net.get('mask')
    info['Gateway'] = net.get('gateway')
    info['Device Time'] = conn.get_time()
    info['Firmware Version'] = conn.get_firmware_version()
    info['Platform'] = conn.get_platform()
    info['Device Name'] = conn.get_device_name()
    info['Pin Width'] = conn.get_pin_width()
    info['Serial Number'] = conn.get_serialnumber()
    info['MAC'] = conn.get_mac()
    return info

def fetch_device_snapshot(device_entry, args):
    """Connect to a single device and return its info map plus optional error."""
    ip = device_entry.get('ip') or device_entry.get('address')
    if not ip:
        return {}, 'missing ip'
    port = device_entry.get('port', args.port)
    password = device_entry.get('password', args.password)
    conn_local = None
    try:
        zk_local = ZK(ip, port=port, timeout=args.timeout, password=password, force_udp=args.force_udp, verbose=args.verbose)
        conn_local = zk_local.connect()
        sdk_build = conn_local.set_sdk_build_1()
        conn_local.disable_device()
        info = build_device_info(conn_local, sdk_build)
        return info, ''
    except Exception as exc:
        return {}, str(exc)
    finally:
        if conn_local:
            try:
                conn_local.enable_device()
            except Exception:
                pass
            conn_local.disconnect()

def export_devices_to_csv(args):
    """Load devices from JSON and export their info to CSV."""
    with open(args.devices_json, 'r', encoding='utf-8-sig') as handle:
        data = json.load(handle)
    devices = data.get('devices', data)
    if not isinstance(devices, list):
        raise ValueError('devices.json must contain a list under "devices" or be a list itself')
    fieldnames = []
    for device in devices:
        for key in device.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    if 'error' not in fieldnames:
        fieldnames.append('error')
    for key in DEVICE_INFO_FIELDS:
        if key not in fieldnames:
            fieldnames.append(key)
    output_path = args.devices_csv or 'devices_export.csv'
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for device in devices:
            row = {key: device.get(key, '') for key in fieldnames}
            info, error = fetch_device_snapshot(device, args)
            row['error'] = error
            for key in DEVICE_INFO_FIELDS:
                row[key] = info.get(key, '') if info else ''
            writer.writerow(row)
    print('Exported {} devices to {}'.format(len(devices), output_path))

def print_feature_table(options):
    """Render a simple table describing the available feature switches."""
    def on_off(value, extra=''):
        if not value:
            return 'OFF'
        return 'ON{}'.format(extra)

    rows = [
        ('Basic Info', '-b/--basic', on_off(options.basic), 'Skip bulk reads'),
        ('Force UDP', '-f/--force-udp', on_off(options.force_udp), 'Force UDP transport'),
        ('Verbose', '-v/--verbose', on_off(options.verbose), 'Print debug info'),
        ('Templates', '-t/--templates', on_off(options.templates), 'Compare template reads'),
        ('Templates Raw', '-tr/--templates-raw', on_off(options.templates_raw), 'Dump templates'),
        ('Templates Index', '-ti/--templates-index', on_off(options.templates_index, ' ({})'.format(options.templates_index) if options.templates_index else ''), 'Read single template'),
        ('Records', '-r/--records', on_off(options.records), 'Fetch attendance logs'),
        ('Update Time', '-u/--updatetime', on_off(options.updatetime), 'Sync device clock'),
        ('Live Capture', '-l/--live-capture', on_off(options.live_capture), 'Stream live events'),
        ('Open Door', '-o/--open-door', on_off(options.open_door), 'Unlock once (10s)'),
        ('Open Door Continuous', '-oc/--open-door-continuous', on_off(options.open_door_continuous, ' ({}s)'.format(options.open_door_continuous) if options.open_door_continuous else ''), 'Keep unlocking'),
        ('Delete User', '-D/--deleteuser', on_off(options.deleteuser, ' (#%s)' % options.deleteuser if options.deleteuser else ''), 'Remove user by UID'),
        ('Add User', '-A/--adduser', on_off(options.adduser, ' (#%s)' % options.adduser if options.adduser else ''), 'Create/update user'),
        ('Enroll User', '-E/--enrolluser', on_off(options.enrolluser, ' (#%s)' % options.enrolluser if options.enrolluser else ''), 'Enroll fingerprint'),
        ('Devices JSON', '--devices-json', on_off(options.devices_json, ' ({})'.format(options.devices_json) if options.devices_json else ''), 'Bulk export source file'),
        ('Devices CSV', '--devices-csv', on_off(options.devices_csv, ' ({})'.format(options.devices_csv)), 'Bulk export destination'),
    ]
    render_table('Feature Configuration', ('Feature', 'Arguments', 'Enabled', 'Description'), rows)

parser = argparse.ArgumentParser(description='ZK Basic Reading Tests')
parser.add_argument('-a', '--address', 
                    help='ZK device Address [192.168.1.130]', default='192.168.1.130')
parser.add_argument('-p', '--port', type=int,
                    help='ZK device port [4370]', default=4370)
parser.add_argument('-T', '--timeout', type=int,
                    help='Default [30] seconds (0: disable timeout)', default=30)
parser.add_argument('-P', '--password', type=int,
                    help='Device code/password', default=0)
parser.add_argument('-b', '--basic', action="store_true",
                    help='get Basic Information only. (no bulk read, ie: users)')
parser.add_argument('-f', '--force-udp', action="store_true",
                    help='Force UDP communication')
parser.add_argument('-v', '--verbose', action="store_true",
                    help='Print debug information')
parser.add_argument('-t', '--templates', action="store_true",
                    help='Get templates / fingers (compare bulk and single read)')
parser.add_argument('-tr', '--templates-raw', action="store_true",
                    help='Get raw templates (dump templates)')
parser.add_argument('-ti', '--templates-index', type=int,
                    help='Get specific template', default=0)
parser.add_argument('-r', '--records', action="store_true",
                    help='Get attendance records')
parser.add_argument('-u', '--updatetime', action="store_true",
                    help='Update Date/Time')
parser.add_argument('-l', '--live-capture', action="store_true",
                    help='Live Event Capture')
parser.add_argument('-o', '--open-door', action="store_true",
                    help='Open door')
parser.add_argument('-oc', '--open-door-continuous', type=int, nargs='?', const=10, default=0,
                    help='Continuously open door; optionally set duration for each unlock (default 10s)')
parser.add_argument('-D', '--deleteuser', type=int,
                    help='Delete a User (uid)', default=0)
parser.add_argument('-A', '--adduser', type=int,
                    help='Add a User (uid) (and enroll)', default=0)
parser.add_argument('-E', '--enrolluser', type=int,
                    help='Enroll a User (uid)', default=0)
parser.add_argument('-F', '--finger', type=int,
                    help='Finger for enroll (fid=0)', default=0)
parser.add_argument('--devices-json', default=None,
                    help='Path to a devices.json file for bulk export')
parser.add_argument('--devices-csv', nargs='?', const='devices_export.csv', default=None,
                    help='Output CSV path for bulk export (defaults to devices_export.csv)')

args = parser.parse_args()
bulk_requested = bool(args.devices_json or args.devices_csv)
if bulk_requested:
    if not args.devices_json:
        default_json = 'devices.json'
        if os.path.exists(default_json):
            args.devices_json = default_json
        else:
            print('Bulk export requested but no devices JSON provided and default "{}" not found.'.format(default_json))
            sys.exit(1)
    if not args.devices_csv:
        args.devices_csv = 'devices_export.csv'

print_feature_table(args)

if bulk_requested:
    export_devices_to_csv(args)
    sys.exit(0)

zk = ZK(args.address, port=args.port, timeout=args.timeout, password=args.password, force_udp=args.force_udp, verbose=args.verbose)
try:
    print('Connecting to device ...')
    conn = zk.connect()
    sdk_build = conn.set_sdk_build_1() # why?
    print ('Disabling device ...')
    conn.disable_device()
    now = datetime.datetime.today().replace(microsecond=0)
    if args.updatetime:
        announce_section('Updating Time')
        conn.set_time(now)
        add_result('Time Update', 'OK', 'Device time set to {}'.format(now))
    device_info_map = build_device_info(conn, sdk_build)
    zk_time = device_info_map.get('Device Time')
    dif = abs(zk_time - now).total_seconds()
    if dif > 120:
        print("WRN: TIME IS NOT SYNC!!!!!! (local: %s) use command -u to update" % now)
    add_result('Connection', 'OK', 'Connected to {}:{}'.format(args.address, args.port))
    add_result('Time Drift', 'WARN' if dif > 120 else 'OK', '{}s difference'.format(int(dif)))
    render_keyvalue_table('Device Information', device_info_rows(device_info_map))
    render_sizes_table(conn, 'Sizes & Capacity (Before)')
    if args.basic:
        add_result('Mode', 'INFO', 'Basic information only')
        raise BasicException("Basic Info... Done!")
    announce_section('Load Users')
    inicio = time.time()
    users = conn.get_users()
    final = time.time()
    print ('    took {:.3f}[s]'.format(final - inicio))
    add_result('Users', 'OK', 'Fetched {} users'.format(len(users)))
    target_uid = args.adduser if args.adduser else None
    initial_rows, prev = collect_user_rows(users, target_uid)
    if args.deleteuser:
        announce_section('Delete User UID#{}'.format(args.deleteuser))
        conn.delete_user(args.deleteuser)
        add_result('Delete User', 'OK', 'Removed UID {}'.format(args.deleteuser))
        users = conn.get_users() #update
        user_rows, prev_after = collect_user_rows(users, target_uid)
        if prev is None:
            prev = prev_after
    else:
        user_rows = initial_rows
    render_table('Users Overview', ('UID', 'Name', 'Privilege', 'Group', 'User ID', 'Password', 'Card'), user_rows)
    print ('    took {:.3f}[s]'.format(final - inicio))

    if args.adduser:
        uid = int(args.adduser)
        if prev:
            user = prev
            privilege = 'User' if user.privilege == const.USER_DEFAULT else 'Admin-%s' % user.privilege
            announce_section('Modify User #{}'.format(user.uid))
            print ('-> UID #{:<5} Name     : {:<27} Privilege : {}'.format(user.uid, user.name, privilege))
            print ('              Group ID : {:<8} User ID : {:<8} Password  : {:<8} Card : {}'.format(user.group_id, user.user_id, user.password, user.card))
            #discard prev
        else:
            announce_section('Add User #{}'.format(uid))
        name = input('Name       :')
        admin = input('Admin (y/N):')
        privilege = 14 if admin == 'y' else 0
        password = input('Password   :')
        user_id = input('User ID2   :')
        card = input('Card       :')
        card = int(card) if card else 0
        #if prev:
        #    conn.delete_user(uid) #borrado previo
        try:
            conn.set_user(uid, name, privilege, password, '', user_id, card)
            args.enrolluser = uid
            add_result('Add User', 'OK', 'UID {}'.format(uid))
        except ZKErrorResponse as e:
            print ("error: %s" % e)
            #try new format
            zk_user = User(uid, name, privilege, password, '', user_id, card)
            conn.save_user_template(zk_user)# forced creation
            args.enrolluser = uid
            add_result('Add User', 'WARN', 'Forced template for UID {}'.format(uid))
        conn.refresh_data()

    if args.enrolluser:
        uid = int(args.enrolluser)
        announce_section('Enroll User #{}'.format(uid))
        conn.delete_user_template(uid, args.finger)
        conn.reg_event(0xFFFF) #
        if conn.enroll_user(uid, args.finger):
            conn.test_voice(18) # register ok
            tem = conn.get_user_template(uid, args.finger)
            print (tem)
            add_result('Enroll User', 'OK', 'UID {} finger {}'.format(uid, args.finger))
        else:
            conn.test_voice(23) # not registered
            add_result('Enroll User', 'FAIL', 'UID {} finger {}'.format(uid, args.finger))
        conn.refresh_data()
    #print ("Voice Test ...")
    #conn.test_voice(10)
    if args.templates_index:
        print ("Read Single template... {}".format(args.templates_index))
        inicio = time.time()
        template = conn.get_user_template(args.templates_index, args.finger)
        final = time.time()
        print ('    took {:.3f}[s]'.format(final - inicio))
        print (" single! {}".format(template))
        add_result('Template Single', 'OK' if template else 'WARN', 'UID {} finger {}'.format(args.templates_index, args.finger))
    elif args.templates or args.templates_raw:
        print ("Read Templates...")
        inicio = time.time()
        templates = conn.get_templates()
        final = time.time()
        print ('    took {:.3f}[s]'.format(final - inicio))
        add_result('Templates', 'OK', 'Fetched {} templates'.format(len(templates)))
        if args.templates:
            print ('now checking individually...')
            i = 0
            for tem in templates:
                i += 1
                tem2 =conn.get_user_template(tem.uid,tem.fid)
                if tem2 is None:
                    print ("%i: bulk! %s" % (i, tem))
                elif tem == tem2: # compare with alternative method
                    print ("%i: OK! %s" % (i, tem))
                else:
                    print ("%i: dif-1 %s" % (i, tem))
                    print ("%i: dif-2 %s" % (i, tem2))
            print ('    took {:.3f}[s]'.format(final - inicio))
        else:
            print ('template dump')
            i = 0
            for tem in templates:
                i += 1
                print ("%i:  %s" % (i, tem.dump()))
            print ('    took {:.3f}[s]'.format(final - inicio))

    if args.records:
        print ("Read Records...")
        inicio = time.time()
        attendance = conn.get_attendance()
        final = time.time()
        print ('    took {:.3f}[s]'.format(final - inicio))
        add_result('Records', 'OK', 'Fetched {} events'.format(len(attendance)))
        i = 0
        for att in attendance:
            i += 1
            print ("ATT {:>6}: uid:{:>3}, user_id:{:>8} t: {}, s:{} p:{}".format(i, att.uid, att.user_id, att.timestamp, att.status, att.punch))
        print ('    took {:.3f}[s]'.format(final - inicio))
    render_sizes_table(conn, 'Sizes & Capacity (After)')
    if args.open_door:
        announce_section('Open Door (10s)')
        conn.unlock(10)
        print ('    Door unlocked successfully')
        add_result('Open Door', 'OK', 'Unlocked for 10s')
    if args.open_door_continuous:
        duration = max(1, args.open_door_continuous)
        announce_section('Continuous Door Opening (Ctrl+C to stop)')
        try:
            while True:
                conn.unlock(duration)
                time.sleep(duration)
        except KeyboardInterrupt:
            print ('    Continuous opening stopped')
            add_result('Open Door Continuous', 'OK', 'Loop stopped, duration {}s'.format(duration))
    if args.live_capture:
        announce_section('Live Capture (Ctrl+C to stop)')
        counter = 0
        captured_events = 0
        for att in conn.live_capture():# using a generator!
            if att is None:
                #counter += 1 #enable to implemet a poorman timeout
                print ("timeout {}".format(counter))
            else:
                captured_events += 1
                print ("ATT {:>6}: uid:{:>3}, user_id:{:>8} t: {}, s:{} p:{}".format(counter, att.uid, att.user_id, att.timestamp, att.status, att.punch))
            if counter >= 10:
                conn.end_live_capture = True
        print('')
        print(styled_title('Capture End'))
        add_result('Live Capture', 'OK', '{} events captured'.format(captured_events))
    print ('')
except BasicException as e:
    print (e)
    print ('')
    add_result('Run', 'INFO', str(e))
except Exception as e:
    print ("Process terminate : {}".format(e))
    print ("Error: %s" % sys.exc_info()[0])
    print ('-'*60)
    traceback.print_exc(file=sys.stdout)
    print ('-'*60)
    add_result('Run', 'FAIL', str(e))
finally:
    render_execution_results('Execution Results', results)
    if conn:
        print ('\nEnabling device ...')
        conn.enable_device()
        conn.disconnect()
        print ('Ok byebye!')
        print ('')
