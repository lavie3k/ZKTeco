
from zk import ZK, const
import time
import csv
import sqlite3
import json
from datetime import datetime


def init_database(db_file="zkteco.db"):
    """Initialize SQLite database with attendance/users tables, including device_ip (keep old data)"""
    try:
        db_conn = sqlite3.connect(db_file)
        cursor = db_conn.cursor()

        # Only create tables if they do not exist, do not delete old data
        # cursor.execute('DROP TABLE IF EXISTS attendance')  # Commented to keep data
        # cursor.execute('DROP TABLE IF EXISTS users')       # Commented to keep data

        # Attendance table includes device_ip, name, and unique constraint
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_ip TEXT NOT NULL,
                uid INTEGER,
                user_id TEXT NOT NULL,
                name TEXT,
                timestamp TIMESTAMP,
                status INTEGER,
                punch INTEGER,
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(device_ip, user_id, timestamp)
            )
        ''')

        # Users table includes device_ip and unique constraint on (device_ip, uid)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_ip TEXT NOT NULL,
                uid INTEGER,
                name TEXT,
                privilege TEXT,
                password TEXT,
                group_id TEXT,
                user_id TEXT,
                card TEXT,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(device_ip, uid)
            )
        ''')

        db_conn.commit()
        db_conn.close()
        print(f"✓ Database initialized: {db_file}")
    except Exception as err:
        print(f"✗ Database initialization error: {err}")


def save_attendance_to_db(attendances, device_ip, users_dict, db_file="zkteco.db"):
    """Save attendance records into SQLite, optimized speed, include name from users"""
    if not attendances:
        print("No attendance data to save.")
        return

    try:
        print(f"Connecting to database {db_file}...")
        db_conn = sqlite3.connect(db_file)
        db_conn.isolation_level = None
        db_conn.execute("PRAGMA synchronous = OFF")
        db_conn.execute("PRAGMA cache_size = 50000")
        db_conn.execute("PRAGMA temp_store = MEMORY")
        cursor = db_conn.cursor()

        inserted = 0
        errors = 0
        skipped = 0

        print(f"Starting to process {len(attendances)} records...\n")

        batch = []

        for idx, att in enumerate(attendances):
            try:
                if not hasattr(att, 'user_id') or not hasattr(att, 'timestamp'):
                    skipped += 1
                    continue

                try:
                    uid = int(getattr(att, 'uid', 0))
                except (ValueError, TypeError):
                    uid = 0

                user_id = str(att.user_id).strip()
                timestamp = str(att.timestamp).strip()

                try:
                    status = int(getattr(att, 'status', 0))
                except (ValueError, TypeError):
                    status = 0

                try:
                    punch = int(getattr(att, 'punch', 0))
                except (ValueError, TypeError):
                    punch = 0

                if not user_id:
                    skipped += 1
                    continue

                # Get name from users_dict (uid/user_id -> name mapping)
                name = users_dict.get(str(uid), "") or users_dict.get(user_id, "")

                batch.append((device_ip, uid, user_id, name, timestamp, status, punch))

                if len(batch) >= 1000:
                    try:
                        cursor.executemany('''
                            INSERT OR IGNORE INTO attendance (device_ip, uid, user_id, name, timestamp, status, punch)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', batch)
                        inserted += len(batch)
                        print(f"Progress: {inserted} records saved...")
                    except Exception as e:
                        errors += len(batch)
                        if errors <= 3:
                            print(f"⚠️  Batch error: {e}")
                    batch = []

            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"⚠️  Record error {idx}: {type(e).__name__}: {str(e)[:100]}")
                continue

        if batch:
            try:
                cursor.executemany('''
                    INSERT OR IGNORE INTO attendance (device_ip, uid, user_id, name, timestamp, status, punch)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', batch)
                inserted += len(batch)
            except Exception as e:
                errors += len(batch)

        db_conn.commit()
        db_conn.execute("PRAGMA synchronous = FULL")
        db_conn.close()

        print(f"\n✓ Database save completed:")
        print(f"  - New records: {inserted}")
        print(f"  - Skipped records: {skipped}")
        print(f"  - Errors: {errors}")

    except Exception as err:
        print(f"\n✗ Error saving to database: {err}")
        import traceback
        traceback.print_exc()


def save_users_to_db(users, device_ip, db_file="zkteco.db"):
    """Save users list into SQLite including device_ip, optimized speed"""
    try:
        db_conn = sqlite3.connect(db_file)
        db_conn.execute("PRAGMA synchronous = OFF")  # Disable sync
        db_conn.execute("PRAGMA cache_size = 50000")
        cursor = db_conn.cursor()

        # Batch insert
        batch = []
        for user in users:
            try:
                privilege = "Admin" if user.privilege == const.USER_ADMIN else "User"
                uid = user.uid
                name = user.name or ""
                password = user.password or ""
                group_id = user.group_id or ""
                user_id = user.user_id or ""
                card = str(user.card) if hasattr(user, 'card') and user.card else ""

                batch.append((device_ip, uid, name, privilege, password, group_id, user_id, card))
            except Exception:
                continue

        # Bulk insert
        cursor.executemany('''
            INSERT OR REPLACE INTO users (device_ip, uid, name, privilege, password, group_id, user_id, card)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', batch)

        db_conn.commit()
        db_conn.execute("PRAGMA synchronous = FULL")
        db_conn.close()

        print(f"✓ Users saved: {len(batch)} records")
    except Exception as err:
        print(f"✗ Error saving users: {err}")


def print_users_table(users):
    # Render a simple ASCII table for user info
    headers = ["UID", "Name", "Privilege", "Password", "Group ID", "User ID", "Card"]
    rows = []
    for user in users:
        privilege = "Admin" if user.privilege == const.USER_ADMIN else "User"
        card = str(user.card) if hasattr(user, 'card') and user.card else ""
        rows.append([
            str(user.uid),
            user.name or "",
            privilege,
            user.password or "",
            str(user.group_id),
            str(user.user_id),
            card,
        ])

    if not rows:
        print("No data to display.")
        return

    # Compute column widths
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(str(col))) for w, col in zip(widths, row)]

    def fmt_row(row_values):
        return " | ".join(str(col).ljust(w) for col, w in zip(row_values, widths))

    # Build separator line
    separator = "-+-".join("-" * w for w in widths)

    print()
    print(fmt_row(headers))
    print(separator)
    for row in rows:
        print(fmt_row(row))
    print()


def export_users_csv(users, device_ip="unknown", filepath=None):
    # Export user list to CSV with device_ip and timestamp in filename
    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ip_safe = device_ip.replace(".", "_")
        filepath = f"Output/users_export_{ip_safe}_{timestamp}.csv"

    headers = ["UID", "Name", "Privilege", "Password", "Group ID", "User ID", "Card"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for user in users:
            privilege = "Admin" if user.privilege == const.USER_ADMIN else "User"
            card = str(user.card) if hasattr(user, 'card') and user.card else ""
            writer.writerow([
                user.uid,
                user.name or "",
                privilege,
                user.password or "",
                user.group_id,
                user.user_id,
                card,
            ])
    print(f"CSV exported: {filepath}")


def load_devices(filepath="devices.json"):
    """Load the list of attendance devices from JSON file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('devices', [])
    except FileNotFoundError:
        print(f"File not found: {filepath}")
        return []
    except Exception as err:
        print(f"Error reading {filepath}: {err}")
        return []


def display_devices(devices):
    """Display the list of attendance devices in a table"""
    if not devices:
        print("No attendance devices in the list.")
        return

    headers = ["#", "IP", "Device Name", "Location", "Status", "Installed", "Expired", "Notes"]
    rows = []

    for idx, device in enumerate(devices, 1):
        rows.append([
            str(idx),
            device.get('ip', 'N/A'),
            device.get('name', 'N/A'),
            device.get('location', 'N/A'),
            device.get('status', 'N/A'),
            device.get('date_installed', 'N/A'),
            device.get('date_expired', 'N/A'),
            device.get('notes', 'N/A'),
        ])

    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(str(col))) for w, col in zip(widths, row)]

    def fmt_row(row_values):
        return " | ".join(str(col).ljust(w) for col, w in zip(row_values, widths))

    separator = "-+-".join("-" * w for w in widths)
    print()
    print(fmt_row(headers))
    print(separator)
    for row in rows:
        print(fmt_row(row))
    print()


def select_device(devices):
    """Allow selecting an attendance device from the list"""
    if not devices:
        print("No attendance devices.")
        return None

    display_devices(devices)

    while True:
        try:
            choice = input("Enter the device number (or 'q' to skip): ").strip()
            if choice.lower() == 'q':
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(devices):
                selected = devices[idx]
                print(f"\n✓ Selected: {selected.get('name', 'N/A')} ({selected.get('ip', 'N/A')})")
                return selected.get('ip')
            else:
                print(f"Invalid choice. Please enter from 1 to {len(devices)}.")
        except ValueError:
            print("Please enter a number or 'q'.")


def sync_all_devices_users(devices, db_file="zkteco.db"):
    """Fetch users from all attendance devices and save to database"""
    print("\n" + "="*60)
    print("SYNC USERS FROM ALL ATTENDANCE DEVICES")
    print("="*60)

    total_users = 0
    success_count = 0
    failed_devices = []

    for idx, device in enumerate(devices, 1):
        device_ip = device.get('ip')
        device_name = device.get('name', 'N/A')

        print(f"\n[{idx}/{len(devices)}] Connecting to {device_name} ({device_ip})...")

        try:
            zk = ZK(device_ip, port=4370, timeout=30, password=0, force_udp=True, ommit_ping=False)
            conn = zk.connect()
            conn.disable_device()

            print(f"  → Fetching users...")
            users = conn.get_users()
            print(f"  → Found {len(users)} users")

            if users:
                save_users_to_db(users, device_ip, db_file)
                total_users += len(users)
                success_count += 1

            conn.enable_device()
            conn.disconnect()
            print(f"  ✓ Done!")

        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed_devices.append(f"{device_name} ({device_ip})")
            continue

    print("\n" + "="*60)
    print("USER SYNC RESULTS")
    print("="*60)
    print(f"Success: {success_count}/{len(devices)} devices")
    print(f"Total users: {total_users}")
    if failed_devices:
        print(f"\nFailed devices:")
        for dev in failed_devices:
            print(f"  - {dev}")
    print("="*60 + "\n")


def sync_all_devices_attendance(devices, db_file="zkteco.db"):
    """Fetch attendance logs from all devices and save to database"""
    print("\n" + "="*60)
    print("SYNC ATTENDANCE FROM ALL ATTENDANCE DEVICES")
    print("="*60)

    total_records = 0
    success_count = 0
    failed_devices = []

    for idx, device in enumerate(devices, 1):
        device_ip = device.get('ip')
        device_name = device.get('name', 'N/A')

        print(f"\n[{idx}/{len(devices)}] Connecting to {device_name} ({device_ip})...")

        try:
            zk = ZK(device_ip, port=4370, timeout=30, password=0, force_udp=True, ommit_ping=False)
            conn = zk.connect()
            conn.disable_device()

            # Fetch users first for name mapping
            print(f"  → Fetching users...")
            users = conn.get_users()
            users_dict = {}
            for user in users:
                users_dict[str(user.uid)] = user.name or ""
                users_dict[user.user_id] = user.name or ""

            print(f"  → Fetching attendance logs...")
            attendances = conn.get_attendance()
            print(f"  → Found {len(attendances)} records")

            if attendances:
                save_attendance_to_db(attendances, device_ip, users_dict, db_file)
                total_records += len(attendances)
                success_count += 1

            conn.enable_device()
            conn.disconnect()
            print(f"  ✓ Done!")

        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed_devices.append(f"{device_name} ({device_ip})")
            continue

    print("\n" + "="*60)
    print("ATTENDANCE SYNC RESULTS")
    print("="*60)
    print(f"Success: {success_count}/{len(devices)} devices")
    print(f"Total records: {total_records}")
    if failed_devices:
        print(f"\nFailed devices:")
        for dev in failed_devices:
            print(f"  - {dev}")
    print("="*60 + "\n")


def show_device_info(devices, device_ip):
    """Show detailed information for a device in a table"""
    for device in devices:
        if device.get('ip') == device_ip:
            info_rows = [
                ["IP", device.get('ip', 'N/A')],
                ["Device Name", device.get('name', 'N/A')],
                ["Location", device.get('location', 'N/A')],
                ["Status", device.get('status', 'N/A')],
                ["Install Date", device.get('date_installed', 'N/A')],
                ["Expiry Date", device.get('date_expired', 'N/A')],
                ["Notes", device.get('notes', 'N/A')],
            ]

            widths = [len("Field"), len("Value")]
            for row in info_rows:
                widths = [max(widths[0], len(row[0])), max(widths[1], len(row[1]))]

            def fmt_row(row_values):
                return " | ".join(col.ljust(w) for col, w in zip(row_values, widths))

            print("\n" + "="*(sum(widths) + 3))
            print(fmt_row(["Field", "Value"]))
            print("-"*(sum(widths) + 3))
            for row in info_rows:
                print(fmt_row(row))
            print("="*(sum(widths) + 3) + "\n")
            return
    print(f"Device info not found for {device_ip}\n")


def search_user_by_id(users):
    # Allow interactive lookup by user_id field
    query = input("Enter User ID to search (leave blank to skip): ").strip()
    if not query:
        print("Search skipped.")
        return
    matched = [u for u in users if str(u.user_id) == query]
    if matched:
        print(f"Found {len(matched)} result(s) with User ID = {query}:")
        print_users_table(matched)
    else:
        print(f"User ID = {query} not found.")


def search_user_by_name(users):
    """Search users by name (case-insensitive, keyword supported)"""
    query = input("Enter a name or keyword to search (leave blank to skip): ").strip()
    if not query:
        print("Search skipped.")
        return

    query_lower = query.lower()
    matched = [u for u in users if query_lower in (u.name or "").lower()]

    if matched:
        print(f"\nFound {len(matched)} result(s) containing '{query}':")
        print_users_table(matched)
    else:
        print(f"No users found containing '{query}' in the name.")


def search_user_admin(users):
    """List all users whose privilege is Admin"""
    admin_users = [u for u in users if u.privilege == const.USER_ADMIN]

    if admin_users:
        print(f"\nFound {len(admin_users)} Admin account(s):")
        print_users_table(admin_users)
    else:
        print("No Admin accounts found in the list.")


def print_attendance_table(attendances):
    # Render attendance records as ASCII table
    headers = ["UID", "User ID", "Timestamp", "Status", "Punch"]
    status_map = {0: "Check-In", 1: "Check-Out", 2: "Break-Out", 3: "Break-In", 4: "OT-In", 5: "OT-Out"}

    rows = []
    for att in attendances:
        try:
            uid = str(getattr(att, 'uid', ''))
            user_id = str(getattr(att, 'user_id', ''))
            timestamp = str(getattr(att, 'timestamp', ''))
            status_code = getattr(att, 'status', None)
            status = status_map.get(status_code, str(status_code)) if status_code is not None else ''
            punch = str(getattr(att, 'punch', ''))

            rows.append([uid, user_id, timestamp, status, punch])
        except Exception:
            continue

    if not rows:
        print("No data to display.")
        return

    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(str(col))) for w, col in zip(widths, row)]

    def fmt_row(row_values):
        return " | ".join(str(col).ljust(w) for col, w in zip(row_values, widths))

    separator = "-+-".join("-" * w for w in widths)

    print()
    print(fmt_row(headers))
    print(separator)
    for row in rows:
        print(fmt_row(row))
    print()


def get_attendance_interactive(conn, device_ip, users):
    # Get and display attendance records
    try:
        print("Fetching attendance data...")
        attendances = conn.get_attendance()
        print(f"Total attendance records: {len(attendances)}")

        if attendances:
            print_attendance_table(attendances)

            # Save to SQLite
            save_to_db = input("\nSave to SQLite database? (y/N): ").strip().lower()
            if save_to_db in ("y", "yes"):
                # Build mapping uid/user_id -> name from users
                users_dict = {}
                for user in users:
                    users_dict[str(user.uid)] = user.name or ""
                    users_dict[user.user_id] = user.name or ""

                save_attendance_to_db(attendances, device_ip, users_dict)

            # Optional: filter by user_id
            filter_user = input("\nEnter User ID to filter (leave blank to view all): ").strip()
            if filter_user:
                filtered = [a for a in attendances if str(a.user_id) == filter_user]
                if filtered:
                    print(f"\n--- Attendance for User ID {filter_user} ---")
                    print_attendance_table(filtered)
                else:
                    print(f"No attendance found for User ID {filter_user}.")
        else:
            print("No attendance records found.")
    except Exception as err:
        print(f"Error fetching attendance data: {err}")


def live_capture_interactive(conn, users):
    """View live data from the attendance device, display as table, press 'q' to quit"""
    try:
        print("\n" + "="*80)
        print("LIVE CAPTURE FROM ATTENDANCE DEVICE (press 'q' to quit)")
        print("="*80 + "\n")

        # Build mapping uid/user_id -> name from users
        users_dict = {}
        for user in users:
            users_dict[str(user.uid)] = user.name or ""
            users_dict[user.user_id] = user.name or ""

        headers = ["#", "UID", "User ID", "Name", "Timestamp", "Status"]
        status_map = {0: "Check-In", 1: "Check-Out", 2: "Break-Out", 3: "Break-In", 4: "OT-In", 5: "OT-Out"}

        print("Waiting for live data from the device...")
        print()

        counter = 0
        captured_events = 0

        widths = [len(h) for h in headers]

        try:
            for att in conn.live_capture():
                # Check user input (non-blocking)
                import sys, select
                if sys.platform != 'win32':
                    # Linux/Mac - use select
                    if select.select([sys.stdin], [], [], 0)[0]:
                        user_input = sys.stdin.read(1).lower()
                        if user_input == 'q':
                            break
                else:
                    # Windows - check keyboard input
                    import msvcrt
                    if msvcrt.kbhit():
                        user_input = msvcrt.getch().decode().lower()
                        if user_input == 'q':
                            break

                if att is None:
                    # Timeout
                    continue

                captured_events += 1
                counter += 1

                uid = str(getattr(att, 'uid', ''))
                user_id = str(getattr(att, 'user_id', ''))
                timestamp = str(getattr(att, 'timestamp', ''))
                status_code = getattr(att, 'status', None)
                status = status_map.get(status_code, str(status_code)) if status_code is not None else ''

                name = users_dict.get(uid, "") or users_dict.get(user_id, "")

                row = [str(counter), uid, user_id, name, timestamp, status]

                for idx, val in enumerate(row):
                    if idx < len(widths):
                        widths[idx] = max(widths[idx], len(val))

                def fmt_row(values):
                    return " | ".join(val.ljust(w) for val, w in zip(values, widths))

                if counter == 1:
                    print(fmt_row(headers))
                    line = "-+-".join("-" * w for w in widths)
                    print(line)

                print(fmt_row(row))

        except KeyboardInterrupt:
            print("\n\n[Live capture stopped]")

        print("\n" + "="*80)
        print(f"Total captured events: {captured_events}")
        print("="*80 + "\n")

    except Exception as err:
        print(f"Live capture error: {err}")


def create_user_interactive(conn):
    answer = input("Do you want to create a new user? (y/N): ").strip().lower()
    if answer not in ("y", "yes"):
        print("Skipped creating a new user.")
        return

    def prompt(default, label):
        value = input(f"{label} [{default}]: ").strip()
        return value if value else default

    uid = int(prompt("1337", "UID (employee number - 0-65535)"))
    name = prompt("Nguyen Huy Vinh", "Name (Employee name)")
    privilege_input = prompt("Admin", "Privilege (Admin/User)")
    privilege = const.USER_ADMIN if privilege_input == "Admin" else const.USER_DEFAULT
    password = prompt("1337", "Password")
    group_id = prompt("", "Group ID (group - 0-65535)")
    user_id = prompt("01337", "User ID (employee code)")
    card = int(prompt("12345678", "Card (card number - 12345678)"))

    try:
        conn.set_user(
            uid=uid,
            name=name,
            privilege=privilege,
            password=password,
            group_id=group_id,
            user_id=user_id,
            card=card,
        )
        print(f"✓ New user created successfully: UID={uid}, Name={name}, User ID={user_id}")
    except Exception as err:
        print(f"✗ Failed to create user: {err}")


def delete_user_interactive(conn, users):
    """Delete a user from the device"""
    if not users:
        print("No users to delete.")
        return users

    print("\n--- User list ---")
    print_users_table(users)

    answer = input("\nDo you want to delete a user? (y/N): ").strip().lower()
    if answer not in ("y", "yes"):
        print("Skipped deleting user.")
        return users

    uid_input = input("Enter the UID of the user to delete: ").strip()
    if not uid_input:
        print("Skipped deleting user.")
        return users

    try:
        uid = int(uid_input)
        user_found = None
        for user in users:
            if user.uid == uid:
                user_found = user
                break

        if not user_found:
            print(f"✗ User not found with UID={uid}")
            return users

        print(f"\n⚠️  You are deleting this user:")
        print(f"   UID: {user_found.uid}")
        print(f"   Name: {user_found.name}")
        print(f"   User ID: {user_found.user_id}")
        confirm = input("Confirm delete? (type 'yes' to confirm): ").strip().lower()

        if confirm == "yes":
            conn.delete_user(uid)
            print(f"✓ User deleted successfully: UID={uid}, Name={user_found.name}")
            return conn.get_users()
        else:
            print("Delete canceled.")
            return users
    except ValueError:
        print("✗ Invalid UID. Please enter a number.")
        return users
    except Exception as err:
        print(f"✗ Failed to delete user: {err}")
        return users


def edit_user_interactive(conn, users):
    """Edit user information"""
    if not users:
        print("No users to edit.")
        return users

    print("\n--- User list ---")
    print_users_table(users)

    uid_input = input("\nEnter the UID of the user to edit: ").strip()
    if not uid_input:
        print("Skipped editing user.")
        return users

    try:
        uid = int(uid_input)
        user_found = None
        for user in users:
            if user.uid == uid:
                user_found = user
                break

        if not user_found:
            print(f"✗ User not found with UID={uid}")
            return users

        print(f"\n--- Edit User UID={uid} ---")
        print("Old values are shown in []. Press Enter to keep them unchanged.")

        def prompt_with_default(field_name, default_value):
            """Input with displayed default value"""
            default_str = str(default_value) if default_value is not None else ""
            user_input = input(f"{field_name} [{default_str}]: ").strip()
            return user_input if user_input else default_str

        new_uid = int(prompt_with_default("UID", uid))
        new_name = prompt_with_default("Name", user_found.name or "")

        privilege_input = prompt_with_default(
            "Privilege (Admin/User)",
            "Admin" if user_found.privilege == const.USER_ADMIN else "User"
        )
        new_privilege = const.USER_ADMIN if privilege_input == "Admin" else const.USER_DEFAULT

        new_password = prompt_with_default("Password", user_found.password or "")
        new_group_id = prompt_with_default("Group ID", user_found.group_id or "")
        new_user_id = prompt_with_default("User ID", user_found.user_id or "")

        new_card_str = prompt_with_default(
            "Card",
            user_found.card if hasattr(user_found, 'card') and user_found.card else "0"
        )
        try:
            new_card = int(new_card_str) if new_card_str else 0
        except ValueError:
            new_card = 0

        print(f"\n--- New information ---")
        print(f"UID: {new_uid}")
        print(f"Name: {new_name}")
        print(f"Privilege: {'Admin' if new_privilege == const.USER_ADMIN else 'User'}")
        print(f"Password: {new_password}")
        print(f"Group ID: {new_group_id}")
        print(f"User ID: {new_user_id}")
        print(f"Card: {new_card}")

        confirm = input("\nConfirm changes? (type 'yes' to confirm): ").strip().lower()

        if confirm == "yes":
            conn.set_user(
                uid=new_uid,
                name=new_name,
                privilege=new_privilege,
                password=new_password,
                group_id=new_group_id,
                user_id=new_user_id,
                card=new_card,
            )
            print(f"✓ User updated successfully: UID={new_uid}, Name={new_name}")
            return conn.get_users()
        else:
            print("Edit canceled.")
            return users

    except ValueError:
        print("✗ Invalid data. Please enter numbers for UID/Card.")
        return users
    except Exception as err:
        print(f"✗ Failed to edit user: {err}")
        return users


def get_device_ip():
    default_ip = "192.168.1.30"
    print(f"\nCurrent attendance device IP: {default_ip}")
    ip_input = input("Enter new IP (leave blank to keep current): ").strip()
    return ip_input if ip_input else default_ip


def show_menu():
    print("\n" + "="*50)
    print("USER MANAGEMENT MENU - ZK TECO")
    print("="*50)
    print("1. View all users")
    print("2. Create new user")
    print("3. Edit user")
    print("4. Delete user")
    print("5. Find Admin users")
    print("6. Search user by User ID")
    print("7. Search user by Name")
    print("8. View attendance data")
    print("9. View LIVE capture from device")
    print("10. View device list")
    print("11. Sync USERS from ALL devices")
    print("12. Sync ATTENDANCE from ALL devices")
    print("13. Re-enter attendance device IP")
    print("0. Exit")
    print("="*50)


def handle_menu_option(option, conn, users, device_ip, devices):
    if option == "1":
        print("\n--- All users ---")
        if users:
            print_users_table(users)
        else:
            print("No users found.")
    elif option == "2":
        create_user_interactive(conn)
        return conn.get_users(), device_ip
    elif option == "3":
        users = edit_user_interactive(conn, users)
        return users, device_ip
    elif option == "4":
        users = delete_user_interactive(conn, users)
        return users, device_ip
    elif option == "5":
        search_user_admin(users)
    elif option == "6":
        search_user_by_id(users)
    elif option == "7":
        search_user_by_name(users)
    elif option == "8":
        get_attendance_interactive(conn, device_ip, users)
    elif option == "9":
        live_capture_interactive(conn, users)
    elif option == "10":
        print("\n--- Device list management ---")
        selected_ip = select_device(devices)
        if selected_ip:
            device_ip = selected_ip
            show_device_info(devices, device_ip)
        return users, device_ip
    elif option == "11":
        sync_all_devices_users(devices)
        if conn:
            users = conn.get_users()
        return users, device_ip
    elif option == "12":
        sync_all_devices_attendance(devices)
        return users, device_ip
    elif option == "13":
        return users, "change_ip"
    elif option == "0":
        print("Exiting...")
        return None, None
    return users, device_ip


conn = None
device_ip = "192.168.1.30"

# Initialize database
init_database()

# Load device list
devices = load_devices("devices.json")
print(f"Loaded {len(devices)} devices from config file")

try:
    while True:
        # Ask for IP at start or when changed
        if device_ip == "192.168.1.30" or device_ip == "change_ip":
            if device_ip == "change_ip":
                print("\nSelect attendance device:")
                print("1. Choose from list")
                print("2. Enter IP manually")
                choice = input("Choose (1/2): ").strip()
                if choice == "1":
                    selected_ip = select_device(devices)
                    if selected_ip:
                        device_ip = selected_ip
                    else:
                        device_ip = input("Enter attendance device IP: ").strip()
                else:
                    device_ip = input("Enter attendance device IP: ").strip()
            else:
                selected_ip = select_device(devices)
                if selected_ip:
                    device_ip = selected_ip
                    show_device_info(devices, device_ip)
                else:
                    device_ip = input("Enter attendance device IP: ").strip()

        # Create ZK instance
        # Improvement: increase timeout, use force_udp=True (ZK Teco often uses UDP)
        zk = ZK(device_ip, port=4370, timeout=30, password=0, force_udp=True, ommit_ping=False)
        try:
            # Connect to device
            print(f"-> Connecting to device {device_ip}...")
            show_device_info(devices, device_ip)
            conn = zk.connect()
            print("-> Connected successfully!")
            # Disable device during operations
            print("-> Disabling device...")
            conn.disable_device()
            print("-> Device disabled")

            # Fetch initial users list
            print("Fetching users list...")
            users = conn.get_users()
            print(f"Total users: {len(users)}")
            export_users_csv(users, device_ip)

            # Save users to database
            save_users = input("Save user list to database? (y/N): ").strip().lower()
            if save_users in ("y", "yes"):
                save_users_to_db(users, device_ip)

            # Interactive menu loop
            change_ip = False
            while True:
                show_menu()
                choice = input("Select function (0-13): ").strip()

                if choice not in ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"):
                    print("Invalid option. Please choose 0-13.")
                    continue

                result = handle_menu_option(choice, conn, users, device_ip, devices)
                if result is None or result == (None, None):
                    change_ip = False
                    break
                elif isinstance(result, tuple):
                    users, new_device_ip = result
                    if new_device_ip == "change_ip":
                        change_ip = True
                        break
                    elif new_device_ip != device_ip:
                        device_ip = new_device_ip
                        change_ip = True
                        break
                    device_ip = new_device_ip
                else:
                    users = result

            if not change_ip:
                break

            # Test voice: say thank you
            conn.test_voice()
            # Re-enable device after all commands executed
            conn.enable_device()
            conn.disconnect()
        except Exception as e:
            print(f"Connection error: {e}")
            retry = input("Retry connection? (y/N): ").strip().lower()
            if retry not in ("y", "yes"):
                break
except Exception as e:
    print("Process terminate : {}".format(e))
finally:
    if conn:
        conn.disconnect()
