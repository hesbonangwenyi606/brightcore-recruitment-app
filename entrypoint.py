"""Prepare persistent data permissions, then run the app without root."""
import os
import pwd
import sys
from pathlib import Path


def main():
    if os.geteuid() == 0:
        app = pwd.getpwnam("app")
        data_dir = Path("/data")
        upload_dir = Path(os.environ.get("BRIGHTCORE_UPLOADS", "/data/private_uploads"))
        database = Path(os.environ.get("BRIGHTCORE_DB", "/data/brightcore.sqlite3"))

        data_dir.mkdir(parents=True, exist_ok=True)
        upload_dir.mkdir(parents=True, exist_ok=True)
        for path in (data_dir, upload_dir):
            os.chown(path, app.pw_uid, app.pw_gid)
        if database.exists():
            os.chown(database, app.pw_uid, app.pw_gid)

        os.setgroups([])
        os.setgid(app.pw_gid)
        os.setuid(app.pw_uid)

    command = sys.argv[1:] or [sys.executable, "server.py"]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
