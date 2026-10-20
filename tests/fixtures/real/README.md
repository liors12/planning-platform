# Real attachments - kept OUTSIDE this repository

These are a client's design drawings (אאורה, מתחם הטייסים). The repository is
**public**, so committing them would publish them. They live on Lior's Mac:

    ~/planning-platform-fixtures/real/

(override with `GOLDEN_FIXTURES_DIR`). Size was not the constraint: GitHub's
per-file limit is 100 MB (warning at 50 MB) and the largest file is 13 MB;
git LFS is not installed here.

| file | sheet | original name in ~/Downloads | md5 | bytes |
|---|---|---|---|---|
| traffic-12753.1-1_ts-1-3-5.pdf | 12753.1/1 | אאורה מתחם הטייסים - נספח תנועה ראשוני תאי שטח 1,3,5.pdf | 932f6c4fe6b7a65b9a0395b8a2e79432 | 4100453 |
| traffic-12753.1-3_ts-2.pdf | 12753.1/3 | אאורה מתחם הטייסים - נספח תנועה ראשוני תא שטח 2.pdf | ff37760e3599146176bfc44af7636a12 | 1104739 |
| traffic-12753.1-5_ts-4.pdf | 12753.1/5 | אאורה מתחם הטייסים - נספח תנועה ראשוני תא שטח 4.pdf | 8babc85e7fcdbe217aa0eaf1e7974f48 | 1424138 |
| development-189-6-plan-08.pdf | 189-6-plan-08 | אאורה מתחם הטייסים - נספח פיתוח.pdf | 017560b5a7c4170624b7864691fd5609 | 13051344 |

Sheet numbers are read from each title block ("תכנית מס'"); the development
plan's id is in its text layer ("189-6-plan-08.dwg").

`~/Downloads` holds three byte-identical copies of the תא שטח 2 sheet
(`... תא שטח 2.pdf`, `(1)`, `(2)`, all md5 ff37760e); one is kept.

Used by `tests/test_golden_attachment_reports.py` (verdict half - skipped
where these files are absent, i.e. in GitHub CI) and
`tests/test_attachment_readability.py`.
