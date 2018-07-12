# eBay Kleinanzeigen Crawler

eBay Kleinanzeigen crawler library written in Python to store listing pages as json files. Rate limiting defaults to 1qps.

## Setup and test run
```bash
pip3 install -r requirements.txt
./ebkcrawler/crawler.py
open data/results.json
```

## Run tests
```bash
PYTHONPATH='.' py.test
```