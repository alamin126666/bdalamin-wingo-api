# BD ALAMIN WinGo Firebase Collector

A production-oriented Python Telegram bot that runs on Railway, remains online continuously, and starts or stops a separate WinGo result collector when the owner sends `/on` or `/off`. While enabled, the collector fetches the public source API immediately and then schedules later fetches on Bangladesh time's exact minute boundaries (`HH:MM:00`), stores new results in Firebase Realtime Database, prevents duplicate `issueNumber` values, keeps the newest record first, and retains at most 1,000 records.

This project only collects and stores publicly available result data. It does not implement betting, prediction, account access, spam, or credential handling beyond the Firebase service account needed by the database client.

## Project tree

```text
bd-alamin-wingo-firebase/
├── bot.py
├── config.py
├── collector.py
├── firebase_client.py
├── requirements.txt
├── Procfile
├── railway.toml
├── .env.example
├── .gitignore
├── database.rules.json
└── README.md
```

## Requirements

You need Python 3.11 or newer for local development, a Telegram bot token, a numeric Telegram owner ID, a Firebase project with Realtime Database enabled, a Firebase service-account JSON object, a GitHub repository, and a Railway account.

The runtime dependencies are pinned in `requirements.txt`: `aiogram`, `aiohttp`, `firebase-admin`, and `python-dotenv`.

## How it works

The Telegram polling process and collector task are separate. Railway starts `python bot.py`; the collector begins **OFF** after every process restart. `/start` reports the bot and collector state plus the live Firebase record count. `/on` creates one collector task and performs its first fetch immediately. After that first fetch, later cycles are aligned to Bangladesh time's minute boundaries—for example `12:34:00`, `12:35:00`, and `12:36:00`; they are not calculated as 60 seconds from the `/on` command time. Repeated `/on` commands do not create additional loops. `/off` cancels only the collector task and leaves Telegram polling online.

Each source item is keyed by `issueNumber`. The collector reads the existing node, merges unseen source results, orders records by descending issue number, truncates to `MAX_DATA` (never above 1,000), and replaces the database node with one Firebase `set` operation. If that write fails, the existing Firebase data is not changed and the next cycle retries. Firebase Admin SDK calls run in worker threads so they do not block the asyncio event loop.

## 1. Create the Telegram bot

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot`.
3. Choose a display name, for example `BD ALAMIN WinGo Collector`.
4. Choose a unique username ending in `bot`.
5. Copy the token returned by BotFather. Keep it secret; do not commit it to GitHub.
6. Optionally use `/setcommands` and provide:

   ```text
   start - Show collector status and Firebase count
   on - Start the collector
   off - Stop the collector
   ```

## 2. Get the owner Telegram numeric ID

Start a conversation with a trusted Telegram user-ID bot such as [@userinfobot](https://t.me/userinfobot), or use another trusted method to obtain your numeric user ID. Put that number in `OWNER_ID`. The bot silently ignores `/start`, `/on`, and `/off` from every other user.

## 3. Create and configure Firebase

1. Open the [Firebase Console](https://console.firebase.google.com/) and create or select a project.
2. Open **Build → Realtime Database** and create the database in the required region.
3. Copy the database URL, for example `https://your-project-default-rtdb.firebaseio.com`, into `FIREBASE_DB_URL` without a trailing slash.
4. Open **Project settings → Service accounts → Firebase Admin SDK**.
5. Click **Generate new private key** and download the JSON file once. Treat it like a password.
6. For local use, place it beside `bot.py` as `firebase-service-account.json`; this filename is ignored by Git.
7. For Railway, do not upload the file. Convert the JSON object to a single-line JSON string and store it in `FIREBASE_CREDENTIALS_JSON`. For example, from the project directory:

   ```bash
   python -c 'import json; print(json.dumps(json.load(open("firebase-service-account.json"))))'
   ```

   Copy the resulting one-line value into Railway. The application parses it with `json.loads` and never logs it.

### Realtime Database rules

The safest default is to keep client reads and writes disabled and let only the Firebase Admin SDK access the node. The service account bypasses Realtime Database rules, so the collector still works. Import `database.rules.json`, or set equivalent rules manually:

```json
{
  "rules": {
    ".read": false,
    ".write": false
  }
}
```

The Admin SDK uses privileged server credentials and is not equivalent to a public REST request. If you intentionally enable public reads for the result endpoint, anyone who knows the endpoint may be able to read the stored data. Never make the database publicly writable and never expose the service-account JSON.

## 4. Configure local development

Copy the template and edit it:

```bash
cp .env.example .env
```

Set at least:

```dotenv
BOT_TOKEN=your_telegram_bot_token
OWNER_ID=123456789
FIREBASE_DB_URL=https://your-project-default-rtdb.firebaseio.com
FIREBASE_CREDENTIALS_FILE=firebase-service-account.json
```

The default source and collection settings are:

```dotenv
SOURCE_API=https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json
COLLECTION_PATH=WinGo/WinGo_1M/GetHistoryPage
MAX_DATA=1000
INTERVAL=60
REQUEST_TIMEOUT=20
```

`INTERVAL` remains in the configuration for compatibility and is displayed in the bot response, but the collector timing is deliberately aligned to the Bangladesh (`Asia/Dhaka`) minute clock rather than a rolling interval.

Install and run:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## 5. Deploy to GitHub and Railway

1. Create an empty GitHub repository.
2. From this directory, initialize and push the project:

   ```bash
   git init
   git add .
   git commit -m "Initial WinGo Firebase collector"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
   git push -u origin main
   ```

3. In Railway, create a new project and choose **Deploy from GitHub repo**.
4. Select the repository and add these variables under the service's **Variables** tab:

   ```text
   BOT_TOKEN
   OWNER_ID
   FIREBASE_DB_URL
   FIREBASE_CREDENTIALS_JSON
   SOURCE_API
   COLLECTION_PATH
   MAX_DATA
   INTERVAL
   REQUEST_TIMEOUT
   ```

   Use the values from `.env.example`; use `FIREBASE_CREDENTIALS_JSON` rather than committing a credential file. Do not add `FIREBASE_CREDENTIALS_FILE` on Railway unless you deliberately provide a mounted file.

5. Railway detects the `Procfile` or the `railway.toml` start command. The effective command is:

   ```text
   python bot.py
   ```

6. Deploy and open the deployment logs. A healthy startup includes `Firebase Admin SDK initialized` and `Telegram bot started`.
7. Keep the service as a worker/background service rather than adding an unnecessary HTTP server. Railway runs the process continuously and restarts it according to `railway.toml` if it exits.

## 6. Test the workflow

In the owner account, send:

1. `/start` — the collector should report OFF after a fresh Railway deployment and show the dynamic Firebase count.
2. `/on` — the bot should reply that the collector is ON. The logs should immediately show source API fetch, HTTP status, received records, and Firebase total.
3. Wait at least one interval and verify another cycle in Railway logs. Repeated cycles should log duplicate skips for already stored issue numbers.
4. `/off` — the bot should reply that the collector is OFF. Telegram polling remains online.
5. `/start` again — the bot should still respond and show the final count.

The stored node is:

```text
WinGo/WinGo_1M/GetHistoryPage
├── "1"      newest record
├── "2"
├── ...
└── "1000"   oldest retained record
```

If public reads are intentionally enabled, the native Firebase REST endpoint is:

```text
https://YOUR-PROJECT-default-rtdb.firebaseio.com/WinGo/WinGo_1M/GetHistoryPage.json
```

It returns the complete node. This application intentionally does not implement `pageNo` or `pageSize` query parameters.

## 7. Troubleshooting

| Symptom | Check |
| --- | --- |
| Configuration error at startup | Confirm every required variable is present, `OWNER_ID` is numeric, the database URL is an `http(s)` URL, and either `FIREBASE_CREDENTIALS_JSON` or the local credential file exists. |
| Firebase credential JSON error | Ensure the Railway variable contains the complete JSON object, not a filesystem path or a code block. Generate the one-line value with the command above. |
| Bot does not respond | Confirm `BOT_TOKEN` is correct, the Railway service is running, and the owner ID exactly matches the sender's numeric Telegram ID. |
| Unauthorized user gets no response | This is intentional; all commands are owner-only and unauthorized commands are silently ignored. |
| Source API timeout or HTTP error | Review Railway logs. The cycle fails safely and retries on the next interval. |
| Firebase write failed | Check `FIREBASE_DB_URL`, service-account permissions, database availability, and the next cycle's retry log. |
| More than one collector seems active | The code permits only one collector task. Restart the service only after checking whether duplicate log lines came from separate Railway deployments. |
| `/off` stops the bot | Check that only the collector task was cancelled and that Railway did not restart the process for an unrelated failure. |

## Security notes

Never commit `.env`, `firebase-service-account.json`, bot tokens, or `FIREBASE_CREDENTIALS_JSON`. Rotate a token or service-account key immediately if it is exposed. Keep Firebase writes private and restrict Railway project access. The service account is used only server-side by the Admin SDK; it must never be sent to Telegram or returned by the bot.

## Expected workflow

```text
Railway Bot ONLINE
        ↓
Owner /start
        ↓
Collector OFF
        ↓
Owner /on
        ↓
Immediate source fetch
        ↓
Firebase save (new issueNumber values only)
        ↓
Wait INTERVAL seconds
        ↓
Fetch again
        ↓
Duplicate protection
        ↓
Maximum 1000 records, newest first
        ↓
Owner /off
        ↓
Collector OFF
        ↓
Bot remains ONLINE
```
