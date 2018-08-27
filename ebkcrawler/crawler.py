#!/usr/bin/env python3

import json
import logging
import mechanicalsoup
import os

from attrdict import AttrDict
from collections import defaultdict
from datetime import datetime, timedelta
from random import shuffle, randint
from time import sleep
from urllib.parse import urljoin
from telegram import ParseMode
from telegram.ext import CommandHandler, Updater


VERSION = '1.0'
BASE_URL = "https://www.ebay-kleinanzeigen.de/preis:{min_price}:{max_price}/seite:{page_num}/{keywords}/{location}"
OUT_FNAME = 'results.json'
RATE = 1  # wait n seconds between individual requests to ebay
UPDATE_INTERVAL = timedelta(minutes=30)  # wait n seconds between crawl runs

logging.basicConfig(level=logging.DEBUG,
    format='%(asctime)s %(name).24s %(levelname)-8s %(message)s',
    datefmt='%m-%d %H:%M',
    filename='crawler.log')

class Bot(object):
    def __init__(self, crawler):
        logging.getLogger('telegram.bot').setLevel(logging.INFO)
        self.from_json()
        self.crawler = crawler
        self.updater = Updater(token=self.telegram_token)
        dp = self.updater.dispatcher
        dp.add_handler(CommandHandler("start", self.start))
        dp.add_handler(CommandHandler("stop", self.stop))
        dp.add_handler(CommandHandler("suche", self.add_query,
            pass_args=True, pass_chat_data=True))
        self.updater.job_queue.run_repeating(
            self.check_results, UPDATE_INTERVAL, first=3)
        self.updater.start_polling()

    def add_query(self, bot, update, args, chat_data):
        chat_id = update.message.chat_id
        if len(args) == 0:
            update.message.reply_text('Ja ok, und was soll ich suchen? Musst schon die Suchanfrage noch nach /suche schreiben!')
        else:
            keywords = " ".join(args)
            logging.info("Account #{} requested new query '{}'".format(chat_id, keywords))
            self.crawler.add_query(keywords, location='k0l3331', subscriber=chat_id)
            update.message.reply_text('Suchanfrage gestartet')

    def from_json(self):
        try:
            with open('data/bot_data.json') as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}

        if 'ebkcrawler_version' in data:
            assert data['ebkcrawler_version'] == VERSION

        if 'telegram_token' not in data:
            logging.error("""Please add config file data/bot_data.json with 
                key `telegram_token`""")
            raise SystemExit
        self.telegram_token = data['telegram_token']

        if 'sent_links' in data:
            self.sent_links = defaultdict(list, data['sent_links'])
            logging.info("Loaded {} accounts:".format(
                len(self.sent_links.keys())))
        else:
            self.sent_links = defaultdict(list)

    def idle(self):
        return self.updater.idle()

    def send_chat_messages(self, bot, job, query, results):
        reply = "Es gibt neue Ergebnisse für deine Suchanfrage:"
        bot.send_message(query.subscriber, text=reply)

        for i, result in enumerate(results):
            text = "[{title}]({link})**\n\n{price} - {added}".format(
                title=result.title, 
                added=result.added, 
                price=result.price, 
                link=result.link)

            bot.send_message(query.subscriber, 
                text=text, 
                parse_mode=ParseMode.MARKDOWN, 
                disable_web_page_preview=True)

            if result.img is not None:
                bot.send_photo(query.subscriber, result.img)
            logging.info("Sent result #{}: {}".format(i, result.title))
            sleep(0.3)
        
    def check_results(self, bot, job):
        sleep(randint(1, 30))
        for query in crawler.run_queries():
            results = query.recently_added
            logging.info("Crawler found {} new results".format(len(results)))
            unseen = [r for r in results if query.subscriber not in self.sent_links 
                or r.link not in self.sent_links[query.subscriber]]
            logging.info("Sending {} unseen new results".format(len(unseen)))
            if len(unseen) > 0:
                self.send_chat_messages(bot, job, query, unseen)
                self.sent_links[query.subscriber] += [r.link for r in results]
        self.to_json()

    def start(self, bot, update):
        text = """Der Minibuchtbot schickt dir neue Einträge, sobald sie bei 
            eBay Kleinanzeigen eingestellt werden. Starte eine Suche, indem du 
            eine Nachricht `/suche [Suchbegriffe]` schickst. Zum Beispiel
            `/suche 60er kommode`. Es wird automatisch im Gebiet Berlin gesucht."""
        bot.send_message(chat_id=update.message.chat_id, text=text)
        text = """Dieser Bot speichert deine Telegram-ID {}, um dir Nachrichten
            schicken zu können, sowie deine Suchbegriffe und bereits gesendete
            eBay-Anzeigen. Lösche diesen Chat um alle über dich gespeicherten 
            Daten wieder zu löschen.""".format(update.message.chat_id)

    def stop(self, bot, update):
        chat_id = update.message.chat_id
        if chat_id in self.sent_links:
            del self.sent_links[chat_id]
        self.crawler.remove_queries(chat_id)
        text = """Nagut."""
        bot.send_message(chat_id=chat_id, text=text)

    def to_json(self):
        data = {
            'sent_links': self.sent_links,
            'ebkcrawler_version': VERSION,
            'telegram_token': self.telegram_token
        }
        with open('data/bot_data.json', 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


class Crawler(object):
    def __init__(self, target_dir='data', queries=[], debug=False):
        self.browser = mechanicalsoup.Browser()
        self.target_dir = target_dir
        self.outfile = os.path.join(target_dir, OUT_FNAME)
        self.queries = queries
        self.debug = debug
        self.last_query = None
        logging.info("Crawler geladen mit {} Suchanfragen:".format(len(self.queries)))
        for q in self.queries:
            logging.info("{}: {}".format(q.subscriber, q.keywords))

    def add_query(self, keywords, location='k0', max_page=1, min_price=None, 
            max_price=None, subscriber=None):
        logging.info("Adding query '{}' {}p in {}".format(
            keywords, max_page, location))

        if keywords is None or len(keywords) == 0:
            raise ValueError(
                "Query keywords must be a string. Is '{}'".format(keywords))

        existing_query = len([q for q in self.queries if 
            q.keywords == keywords and 
            q.location == location and 
            q.min_price == min_price and 
            q.max_price == max_price and 
            q.subscriber == subscriber]) > 0
        
        if existing_query:
            logging.info("Skipped adding duplicate query")
        else:
            query_entry = AttrDict(
                keywords=keywords,
                location=location,
                max_page=max_page,
                min_price=min_price,
                max_price=max_price,
                results=[],
                recently_added=[],
                subscriber=subscriber
            )
            self.queries.append(query_entry)

            # Init query results
            results = []
            for page_num in range(1, max_page + 1):
                results += self.run_query(query_entry, page_num)
            self.queries[-1]['results'] += results
            self.to_json()

    @classmethod
    def from_json(cls, target_dir='data', *args, **kwargs):
        fname = os.path.join(target_dir, OUT_FNAME)
        with open(fname) as f:
            data = json.load(f)
            assert data['ebkcrawler_version'] == VERSION
            queries = [AttrDict(d) for d in data['queries']]
            return cls(target_dir=target_dir, queries=queries, *args, **kwargs)

    def remove_queries(self, chat_id):
        logging.info("Removing queries for subscriber {}".format(chat_id))
        self.queries = [q for q in self.queries if q.subscriber != chat_id]
        self.to_json()

    def run_queries(self):
        logging.info("Running {} queries".format(len(self.queries)))
        start = datetime.now()
        queries_in_order = [x for x in self.queries]
        shuffle(queries_in_order)
        for i, q in enumerate(queries_in_order):
            sleep(randint(1, 30))
            results = []
            try:
                for page_num in range(1, q.max_page + 1):
                    results += self.run_query(q, page_num)
            except Exception as e:
                logging.error(e)
                if self.debug:
                    raise
            else:
                self.queries[i]['results'] += results
                self.queries[i]['recently_added'] = results
                yield self.queries[i]
        self.to_json()
        logging.info("Completed in {}".format(datetime.now() - start))

    def run_query(self, query, page_num):
        keywords_formatted = '-'.join(query.keywords.lower().split(' '))
        url = BASE_URL.format(
            keywords=keywords_formatted,
            page_num=page_num,
            location=query.location,
            min_price=query.min_price or '',
            max_price=query.max_price or ''
        )

        if self.last_query:
            td = timedelta(seconds=RATE) - (datetime.now() - self.last_query)
            wait_time = td.seconds + td.microseconds / 1E6
            if wait_time <= 1:
                logging.debug("Sleeping {} seconds for rate limiting".format(wait_time))
                sleep(wait_time)
        self.last_query = datetime.now()

        logging.info("Querying for {} in {} (page {})".format(
            query.keywords, query.location, page_num))
        page = self.browser.get(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36'})
        
        with open(os.path.join(self.target_dir, keywords_formatted + str(self.last_query).replace(':', '-') + '.html'), 'w+') as f:
            f.write(page.text)

        results = []
        known_links = set([r.link for r in query.results])
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

            if out.link not in known_links and 'Anzeige' not in out.added:
                results.append(out)
            else:
                logging.debug("Skipped known result {}".format(out.title))

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
    # Load previous crawler results from json file:
    # crawler = Crawler.from_json()
    crawler = Crawler.from_json()
    # crawler.add_query(4325497, 'euro', location='k0l3331', max_page=1)

    bot = Bot(crawler)
    bot.idle()

    # Location string for Berlin = k0l3331
    
    # crawler.run_queries()
    # crawler.to_html(-1)
    crawler.to_json()
