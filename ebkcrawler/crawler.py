#!/usr/bin/env python3

import json
import logging
import mechanicalsoup
import os

from attrdict import AttrDict
from datetime import datetime, timedelta
from time import sleep
from urllib.parse import urljoin


VERSION = '1.0'
BASE_URL = "https://www.ebay-kleinanzeigen.de/seite:{page_num}/{keywords}/{location}"
OUT_FNAME = 'results.json'
RATE = 1  # wait n seconds between queries

# Location Berlin: k0l3331

logging.basicConfig(level=logging.DEBUG,
    format='%(asctime)s %(name).24s %(levelname)-8s %(message)s',
    datefmt='%m-%d %H:%M',
    filename='crawler.log')

class Crawler(object):
    def __init__(self, target_dir='data', queries=[], debug=False):
        self.browser = mechanicalsoup.Browser()
        self.target_dir = target_dir
        self.outfile = os.path.join(target_dir, OUT_FNAME)
        self.queries = queries
        self.debug = debug
        self.last_query = None

    def add_query(self, keywords, location='k0', max_page=1):
        logging.info("Adding query '{}' {}p in {}".format(
            keywords, max_page, location))

        existing_query = len([q for q in self.queries if \
            q.keywords == keywords and \
            location == location]) > 0
        
        if existing_query:
            logging.info("Skipped adding duplicate query")
        else:
            self.queries.append(AttrDict({
                'keywords': keywords,
                'results': [],
                'location': location,
                'max_page': max_page
            }))

    @classmethod
    def from_json(cls, target_dir='data', *args, **kwargs):
        fname = os.path.join(target_dir, OUT_FNAME)
        with open(fname) as f:
            data = json.load(f)
            assert data['ebkcrawler_version'] == VERSION
            queries = [AttrDict(d) for d in data['queries']]
            return cls(target_dir=target_dir, queries=queries, *args, **kwargs)

    def run_queries(self):
        logging.info("Running {} queries".format(len(self.queries)))
        start = datetime.now()
        for i, q in enumerate(self.queries):
            results = []
            try:
                for page_num in range(1, q.max_page + 1):
                    results += self.run_query(q.keywords, page_num, q.location)
            except Exception as e:
                logging.error(e)
                if self.debug:
                    raise
            self.queries[i].results = results
        logging.info("Completed in {}".format(datetime.now() - start))

    def run_query(self, keywords, page_num, location):
        keywords_formatted = '-'.join(keywords.lower().split(' '))
        url = BASE_URL.format(
            keywords=keywords_formatted,
            page_num=page_num,
            location=location
        )

        if self.last_query:
            td = timedelta(seconds=RATE) - (datetime.now() - self.last_query)
            wait_time = td.seconds + td.microseconds / 1E6
            logging.debug("Sleeping {} seconds for rate limiting".format(wait_time))
            sleep(wait_time)
        self.last_query = datetime.now()

        logging.info("Querying for {} in {} (page {})".format(
            keywords, location, page_num))
        page = self.browser.get(url)

        results = []
        for el in page.soup.select('article.aditem'):
            out = AttrDict()
            out.link = urljoin(
                url, el.select('a[href^="/s-anzeige"]')[0].attrs['href'])
            out.title = el.select('.text-module-begin a')[0].text.strip()
            out.desc = el.select('.aditem-main p')[0].text.strip()
            addetails = el.select('.aditem-details')[0]
            out.price = addetails.select('strong')[0].text.strip()
            out.added = el.select('.aditem-addon')[0].text.strip()
            img = el.select('[data-imgsrc]')
            out.img = img[0].attrs['data-imgsrc'] if len(img) else None
            results.append(out)
        return results

    def to_html(self, query_num):
        from jinja2 import Template
        template = Template(open('templates/index.html.tpl').read())
        fname = os.path.join(self.target_dir, 'index.html')
        with open(fname, 'w') as f:
            f.write(template.render(ads=self.queries[query_num].results))

    def to_json(self):
        data = {
            'ebkcrawler_version': VERSION,
            'queries': self.queries
        }
        with open(self.outfile, 'w+') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    crawler = Crawler.from_json()
    crawler.run_queries()
    crawler.to_json()
    crawler.to_html(-1)
