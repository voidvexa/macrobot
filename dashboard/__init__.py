"""Read-only JSON API for the macrobot SQLite database.

This package is a second process beside the cron job. It does not fetch data
and it does not write `observations`, `series_metadata`, or `meta`.
The page is the React app in `dashboard/web`.
"""
