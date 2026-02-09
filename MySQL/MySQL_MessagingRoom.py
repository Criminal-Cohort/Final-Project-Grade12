import mysql.connector as sql
import time
import threading
import sys
import hashlib
import re

last_seen_id = 0
last_seen_id_lock = threading.Lock()


def hash_pw(pw):
  return hashlib.sha256(pw.encode()).hexdigest()


def validate_username(user):
  return (bool(re.fullmatch(r"[A-Za-z0-9_]{3,20}", user)) and user.lower() != "all" and
          user.lower() != "system")


def login(db, users):
  while True:
      users.execute("SELECT username FROM users;")
      usernms = [row[0].lower() for row in users.fetchall()]

      loc = input("1. Sign In\n2. Create Account\nChoose your option (1/2): ")

      if loc == "1":
          user = input("Enter username: ").strip()
          passw = input("Enter password: ").strip()

          users.execute("SELECT pass FROM users WHERE username=%s", (user,))
          row = users.fetchone()

          if row and hash_pw(passw) == row[0]:
              return [user, row[0]]
          else:
              print("Invalid Username or Password\n")

      elif loc == "2":
          user = input("Enter username: ").strip()
          if not validate_username(user):
              print("Invalid username.\n")
              continue

          if user.lower() in usernms:
              print("Username already taken.\n")
              continue

          passw = input("Enter password: ").strip()
          passw2 = input("Re-enter password: ").strip()

          if passw != passw2:
              print("Passwords do not match.\n")
              continue

          hashed_pw = hash_pw(passw)
          users.execute("INSERT INTO users VALUES (%s, %s)", (user, hashed_pw))
          db.commit()
          print("Successfully Registered!\n")
          return [user, hashed_pw]
      else:
          print("Invalid choice. Please choose 1 or 2.\n")


def safe_print(msg):
  sys.stdout.write('\r\033[K')
  print(msg)
  sys.stdout.write(">>> ")
  sys.stdout.flush()

def fetch_messages(user, stop_event):
  db = sql.connect(host="localhost", user="root", passwd="student", database="USERS")
  cursor = db.cursor()
  global last_seen_id

  try:
      while not stop_event.is_set():
          with last_seen_id_lock:
              cursor.execute("""
                  SELECT id, sender, message, receiver FROM messages
                  WHERE (receiver=%s OR receiver='ALL') AND id > %s
                  ORDER BY id ASC
              """, (user, last_seen_id))
              new_messages = cursor.fetchall()

          for msg in new_messages:
              if msg[1] == "System":
                  safe_print(f"> {msg[2]}")

              elif msg[1] != user:
                  if msg[3].upper() == 'ALL':
                      safe_print(f"[{msg[1]}] {msg[2]}")
                  else:
                      safe_print(f"DM [{msg[1]}] {msg[2]}")



              with last_seen_id_lock:
                  last_seen_id = max(last_seen_id, msg[0])

          time.sleep(1)
  except Exception as e:
      safe_print(f"[Thread crash] {e}")

  finally:
      cursor.close()
      db.close()


def main():
  global last_seen_id

  db = sql.connect(host="localhost", user="root", passwd="student")
  cursor = db.cursor()

  cursor.execute("CREATE DATABASE IF NOT EXISTS USERS")
  cursor.close()
  db.close()

  users_db = sql.connect(host="localhost", user="root", passwd="student",
                         database="USERS")
  users = users_db.cursor()

  users.execute("""CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    pass TEXT NOT NULL)""")

  users.execute("""CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    receiver TEXT NOT NULL)""")

  access = login(users_db, users)
  if not access:
      print("Login failed. Exiting.")
      return

  print(f"\nLogged In Successfully as {access[0]}")
  print("Try /help for more details\n")

  sender = access[0]

  users.execute("INSERT INTO messages (sender, message, receiver) VALUES (%s, %s, %s)",
                 ("System", f"User {sender} has joined the room.", "ALL"))
  users_db.commit()

  users.execute("SELECT id FROM messages ORDER BY id DESC LIMIT 1")
  result = users.fetchone()
  last_seen_id = result[0] if result else 0

  stop_event = threading.Event()
  listener_thread = threading.Thread(target=fetch_messages, args=(sender, stop_event),
                                     daemon=True)
  listener_thread.start()

  try:
      while True:
          message = input(">>> ").strip()
          if not message:
              continue

          if message[0] != "/":
              users.execute("INSERT INTO messages (sender, message, receiver)"
                             "VALUES (%s, %s, %s)", (sender, message, "ALL"))
              users_db.commit()
              continue

          command = message.split()

          if command[0] in ["/quit", "/q"]:
              print("Quitting...")
              users.execute("INSERT INTO messages (sender, message, receiver)"   
                             "VALUES (%s, %s, %s)",
                            ("System", f"User {sender} has left the room.", "ALL"))
              users_db.commit()
              stop_event.set()
              listener_thread.join()
              users_db.close()
              quit()


          elif command[0] in ["/logout", "/l"]:
              print("Logging out...")
              users.execute("INSERT INTO messages (sender, message, receiver)"
                             "VALUES (%s, %s, %s)",
                            ("System", f"User {sender} has left the room.", "ALL"))
              users_db.commit()
              break


          elif command[0] in ["/delete", "/d"]:
              pw = input("Enter password to confirm account deletion: ")
              if hash_pw(pw) == access[1]:
                  users.execute("DELETE FROM users WHERE username=%s", (sender,))
                  users.execute("INSERT INTO messages (sender, message, receiver) "
                                "VALUES (%s, %s, %s)",
                                ("System", f"User {sender} has left the room.",
                                            "ALL"))
                  users_db.commit()
                  print("Account deleted.")
                  break
              else:
                  print("Incorrect password.")


          elif command[0] in ["/dm", "/direct", "/whisper", "/w"]:
              if len(command) < 3:
                  print("Usage: /dm <user> <message>")
                  continue
              receiver = command[1]
              dm_message = " ".join(command[2:])
              users.execute("INSERT INTO messages (sender, message, receiver)"
                             "VALUES (%s, %s, %s)", (sender, dm_message, receiver))
              users_db.commit()


          elif command[0] == "/help":
              print("""Available Commands:
  /whisper, /w, /dm, /direct <user> <message> - Send a private message
  /delete, /d - Delete your account
  /logout, /l - Logout and return to login screen
  /quit, /q - Quit the app
  /help - Show this help message
         """)
          else:
              print("Unknown command. Type /help for list.")


  except KeyboardInterrupt:
      print("\nInterrupted by user. Exiting...")

  stop_event.set()
  listener_thread.join()
  users_db.close()
  print("Logged out.\n")



if __name__ == "__main__":
    while True:
        main()
