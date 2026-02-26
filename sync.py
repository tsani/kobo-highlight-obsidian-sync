#!/usr/bin/env python

import asyncio
import uuid
import base64
import sqlite3
import argparse
import os
from os import path
from datetime import datetime
import sys
from notifykit import Notifier, CommonFilter
from pathlib import Path
import json

def die(*args):
    print(*args, file=sys.stderr)
    sys.exit(1)

VAULT_DIR = os.getenv('VAULT_DIR') or die('missing env VAULT_DIR')
UDISKS_ROOT = os.getenv('UDISKS_ROOT') or die('missing env UDISKS_ROOT')
DB_PATH = os.getenv('DB_PATH') or die('missing env DB_PATH')
XDG_STATE_HOME = os.getenv('XDG_STATE_HOME') or \
    path.join(os.getenv('HOME'), '.local', 'share')
STATE_PATH = path.join(XDG_STATE_HOME, 'kobo-highlight-obsidian-sync.json')

DEFAULT_STATE = {
    'as_of_date': datetime.fromtimestamp(0),
}

def make_book_note_path(title):
    return path.join(VAULT_DIR, 'books', title + '.md')

def make_daily_note_path(date):
    return path.join(VAULT_DIR, 'journal', date + '.md')

def load_state():
    if not path.exists(STATE_PATH): return DEFAULT_STATE
    with open(STATE_PATH, 'r') as f:
        d = json.load(f)
    d['as_of_date'] = datetime.fromisoformat(d['as_of_date'])
    return d

def write_state(state):
    with open(STATE_PATH, 'w') as f:
        return json.dump(state, f)

def append_line(f, contents):
    """Appends to the end of a file, creating if it doesn't exist,
    checking whether it ends with \n already and adding one so the contents
    appears on a new line."""
    size = f.tell()
    if size > 0:
        f.seek(-1, 2)
    c = f.read(1)
    f.write((b'\n' if c and c != b'\n' else b'') + contents)

def run_sync_on_db(conn, as_of_date):
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        b.BookmarkID,
        c.Title,
        b.Text AS Highlight,
        b.DateCreated
    FROM Bookmark b JOIN content c ON b.VolumeID = c.ContentID
    WHERE b.Text IS NOT NULL AND c.ContentType = 6
    ORDER BY c.Title, b.DateCreated;
    """)

    latest_highlight_date = datetime.fromtimestamp(0)

    for bookmark_id, title, highlight, isodatestring in cursor.fetchall():
        date = datetime.fromisoformat(isodatestring)
        if date <= as_of_date: continue

        latest_highlight_date = max(date, latest_highlight_date)
        datestring = date.strftime('%Y-%m-%d')

        daily_note_path = make_daily_note_path(datestring)
        book_note_path = make_book_note_path(title)

        highlight = '\n'.join(f'\t> {line}' for line in highlight.split('\n'))
        highlight_entry_text = \
            f'- {datestring} \n{highlight}'
        highlight_entry_bytes = highlight_entry_text.encode('utf-8')

        basic_read_entry_text = \
            f'- [x] #reading [[{title}]] '
        basic_read_entry_bytes = basic_read_entry_text.encode('utf-8')
        full_read_entry_text = \
            basic_read_entry_text + ' ✅ ' + datestring
        full_read_entry_bytes = full_read_entry_text.encode('utf-8')

        # Add fact that I read to the daily note for that day
        # Creates daily note if missing
        # Only adds entry once per book, even if multiple highlights for that book
        with open(daily_note_path, 'a+b') as f:
            f.seek(0,0)
            contents = f.read()
            if basic_read_entry_bytes not in contents:
                append_line(f, full_read_entry_bytes)
                print('added read entry', datestring, 'for', f"'{title}'")

        with open(book_note_path, 'a+b') as f:
            append_line(f, highlight_entry_bytes)
            print('added highlight:', title, datestring)

    return latest_highlight_date

    # XXX This ^ implementation is bad:
    # 1. It reopens the same book file over and over when multiple
    #    highlights are added to the same book.
    #
    # You might want to add an aggregation phase first: set up a map from
    # book titles to highlights for that book. Then iterate thru this map
    # to add all highlights for a particular book in one shot to that
    # book's note.

def run_sync(as_of_date):
    if not path.exists(DB_PATH):
        print(f'fatal: database {DB_PATH} does not exist')
        return as_of_date

    with sqlite3.connect(DB_PATH) as conn:
        latest_highlight_date = run_sync_on_db(conn, as_of_date)
    print('Sync complete')
    if latest_highlight_date > as_of_date:
        write_state({
            'as_of_date': latest_highlight_date.isoformat()
        })
        return latest_highlight_date
    else:
        return as_of_date

async def run_watch(as_of_date):
    notifier = Notifier(
        debounce_ms=200,
        filter=CommonFilter(),
    )
    await notifier.watch([UDISKS_ROOT])
    async for events in notifier:
        if path.exists(DB_PATH):
            print('Database appeared')
            as_of_date = run_sync(as_of_date)

def iso8601_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid ISO8601 timestamp: '{value}'"
        )

def main():
    parser = argparse.ArgumentParser(
        description="Syncs highlights from a KOBO eReader to an Obsidian "
        "vault, either as a one-shot operation or as a daemon.",
    )
    parser.add_argument(
        '--as-of',
        help='only sync highlights as of this ISO8601 timestamp',
        type=iso8601_datetime,
    )
    parser.add_argument(
        '-w', '--watch',
        help='watch for eReader to mount and sync when it appears',
        action='store_true',
    )

    args = parser.parse_args()
    state = load_state()
    as_of_date = args.as_of or state['as_of_date']

    if args.watch:
        asyncio.run(run_watch(as_of_date))
    else:
        run_sync(as_of_date)

if __name__ == '__main__': main()

# Sqlite database schema
# CREATE TABLE content(
#     ContentID TEXT NOT NULL,
#     ContentType TEXT NOT NULL,
#     MimeType TEXT NOT NULL,
#     BookID TEXT,
#     BookTitle TEXT,
#     ImageId TEXT,
#     Title TEXT COLLATE NOCASE,
#     Attribution TEXT COLLATE NOCASE,
#     Description TEXT,
#     DateCreated TEXT,
#     ShortCoverKey TEXT,
#     adobe_location TEXT,
#     Publisher TEXT,
#     IsEncrypted BOOL,
#     DateLastRead TEXT,
#     FirstTimeReading BOOL,
#     ChapterIDBookmarked TEXT,
#     ParagraphBookmarked INTEGER,
#     BookmarkWordOffset INTEGER,
#     NumShortcovers INTEGER,
#     VolumeIndex INTEGER,
#     ___NumPages INTEGER,
#     ReadStatus INTEGER,
#     ___SyncTime TEXT,
#     ___UserID TEXT NOT NULL,
#     PublicationId TEXT,
#     ___FileOffset INTEGER,
#     ___FileSize INTEGER,
#     ___PercentRead INTEGER,
#     ___ExpirationStatus INTEGER,
#     FavouritesIndex NOT NULL DEFAULT -1,
#     Accessibility INTEGER DEFAULT 1,
#     ContentURL TEXT,
#     Language TEXT,
#     BookshelfTags TEXT,
#     IsDownloaded BIT NOT NULL DEFAULT 1,
#     FeedbackType INTEGER DEFAULT 0,
#     AverageRating INTEGER DEFAULT 0,
#     Depth INTEGER,
#     PageProgressDirection TEXT,
#     InWishlist BOOL NOT NULL DEFAULT FALSE,
#     ISBN TEXT,
#     WishlistedDate TEXT DEFAULT "0000-00-00T00:00:00.000",
#     FeedbackTypeSynced INTEGER DEFAULT 0,
#     IsSocialEnabled BOOL NOT NULL DEFAULT TRUE,
#     EpubType INT NOT NULL DEFAULT -1,
#     Monetization INTEGER DEFAULT 2,
#     ExternalId TEXT,
#     Series TEXT,
#     SeriesNumber TEXT,
#     Subtitle TEXT,
#     WordCount INTEGER DEFAULT -1,
#     Fallback TEXT,
#     RestOfBookEstimate INTEGER,
#     CurrentChapterEstimate INTEGER,
#     CurrentChapterProgress FLOAT,
#     PocketStatus INTEGER DEFAULT 0,
#     UnsyncedPocketChanges TEXT,
#     ImageUrl TEXT,
#     DateAdded TEXT,
#     WorkId TEXT,
#     Properties TEXT,
#     RenditionSpread TEXT,
#     RatingCount INTEGER DEFAULT 0,
#     ReviewsSyncDate TEXT,
#     MediaOverlay TEXT,
#     MediaOverlayType TEXT,
#     RedirectPreviewUrl TEXT,
#     PreviewFileSize INTEGER,
#     EntitlementId TEXT,
#     CrossRevisionId TEXT,
#     DownloadUrl TEXT,
#     ReadStateSynced BIT NOT NULL DEFAULT false,
#     TimesStartedReading INTEGER,
#     TimeSpentReading INTEGER,
#     LastTimeStartedReading TEXT,
#     LastTimeFinishedReading TEXT,
#     ApplicableSubscriptions TEXT,
#     ExternalIds TEXT,
#     PurchaseRevisionId TEXT,
#     SeriesID TEXT,
#     SeriesNumberFloat REAL,
#     AdobeLoanExpiration TEXT,
#     HideFromHomePage bit,
#     IsInternetArchive BOOL NOT NULL DEFAULT FALSE,
#     titleKana TEXT,
#     subtitleKana TEXT,
#     seriesKana TEXT,
#     attributionKana TEXT,
#     publisherKana TEXT,
#     IsPurchaseable BOOL DEFAULT TRUE,
#     IsSupported BOOL DEFAULT TRUE,
#     AnnotationsSyncToken TEXT,
#     DateModified TEXT DEFAULT "0000-00-00T00:00:00.000",
#     StorePages INTEGER DEFAULT 0,
#     StoreWordCount INTEGER DEFAULT 0,
#     StoreTimeToReadLowerEstimate INTEGER DEFAULT 0,
#     StoreTimeToReadUpperEstimate INTEGER DEFAULT 0,
#     Duration INTEGER DEFAULT 0,
#     IsAbridged BOOL DEFAULT NULL,
#     SyncConflictType INTEGER DEFAULT 0,
#     PRIMARY KEY (ContentID)
# );
# CREATE INDEX content_bookid_index ON content (BookID);
#
# CREATE TABLE Bookmark (
#     BookmarkID TEXT NOT NULL,
#     VolumeID TEXT NOT NULL,
#     ContentID TEXT NOT NULL,
#     StartContainerPath TEXT NOT NULL,
#     StartContainerChildIndex INTEGER NOT NULL,
#     StartOffset INTEGER NOT NULL,
#     EndContainerPath TEXT NOT NULL,
#     EndContainerChildIndex INTEGER NOT NULL,
#     EndOffset INTEGER NOT NULL,
#     Text TEXT,
#     Annotation TEXT,
#     ExtraAnnotationData BLOB,
#     DateCreated TEXT,
#     ChapterProgress REAL NOT NULL DEFAULT 0,
#     Hidden BOOL NOT NULL DEFAULT 0,
#     Version TEXT,
#     DateModified TEXT,
#     Creator TEXT,
#     UUID TEXT,
#     UserID TEXT,
#     SyncTime TEXT,
#     Published BIT default false,
#     ContextString TEXT,
#     Type TEXT,
#     PRIMARY KEY (BookmarkID) );
# CREATE INDEX bookmark_content ON bookmark (ContentID);
# CREATE INDEX bookmark_volume ON bookmark (VolumeID);
