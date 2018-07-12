#!/usr/bin/env python3

import pytest
import json
from ebkcrawler import Crawler

@pytest.fixture
def crawler(scope='module'):
    return Crawler(target_dir='tests/data', debug=True)

def test_crawler(crawler):
    assert crawler.browser != None

def test_add_query(crawler):
    crawler.add_query('xbox', max_page=2, max_price=90)
    assert crawler.queries[-1]['keywords'] == 'xbox'

def test_duplicate_query(crawler):
    len_before = len(crawler.queries)
    crawler.add_query('xbox', max_page=2)
    assert len(crawler.queries) == len_before

def test_run_queries(crawler):
    crawler.run_queries()
    assert len(crawler.queries[0].results) > 0

def test_to_json(crawler):
    crawler.to_json()
    with open(crawler.outfile) as f:
        output = json.load(f)
        assert len(output['queries']) > 0

def test_to_html(crawler):
    crawler.to_html(-1)
    with open('tests/data/index.html') as f:
        output = f.read()
        assert len(output) > 0
        assert 'xbox' in output