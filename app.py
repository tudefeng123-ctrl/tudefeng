"""Read-only market intelligence service; Python standard library only."""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def now():
    return datetime.now(timezone.utc).isoformat()


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.strip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"').strip("'"))


def request(url, headers=None, payload=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'InvestmentIntelligence/0.1', **(headers or {})},
                                 data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=10) as response:
        data = response.read(4_000_001)
        if len(data) > 4_000_000:
            raise ValueError('response_too_large')
        return data


def unavailable(market, symbol, reason):
    return {'market': market, 'symbol': symbol, 'status': 'unavailable', 'reason': reason, 'retrieved_at': now()}


def quote(market, symbol, price, timestamp, provider, coverage):
    price = float(price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError('invalid_price')
    stamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timestamp_timezone_missing')
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    freshness = 'fresh' if -60 <= age <= 300 else 'stale'
    return {'market': market, 'symbol': symbol, 'price': price, 'as_of': stamp.isoformat(),
            'retrieved_at': now(), 'freshness': freshness, 'status': 'available' if freshness == 'fresh' else 'degraded',
            'source': {'provider': provider, 'coverage': coverage}, 'age_seconds': round(age, 1)}


def fetch_quote(market, symbol):
    try:
        if market == 'us':
            key, secret = os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY')
            if not key or not secret:
                return unavailable(market, symbol, 'missing_credentials')
            obj = json.loads(request(f'https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest?feed=iex',
                                     {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret}))['trade']
            return quote(market, symbol, obj['p'], obj['t'], 'alpaca', 'IEX_SINGLE_EXCHANGE')
        if market == 'crypto':
            rows = json.loads(request(f'https://api.exchange.coinbase.com/products/{symbol}/trades?limit=1'))
            return quote(market, symbol, rows[0]['price'], rows[0]['time'], 'coinbase', 'COINBASE_SPOT')
        if market == 'cn':
            token = os.getenv('TUSHARE_TOKEN')
            if not token:
                return unavailable(market, symbol, 'missing_credentials_or_rt_entitlement')
            obj = json.loads(request('https://api.tushare.pro', {'Content-Type': 'application/json'},
                                     {'api_name': 'rt_k', 'token': token, 'params': {'ts_code': symbol},
                                      'fields': 'ts_code,close,trade_time'}))
            if obj.get('code') != 0:
                return unavailable(market, symbol, 'provider_permission_or_request_error')
            row = dict(zip(obj['data']['fields'], obj['data']['items'][0]))
            stamp = datetime.fromisoformat(row['trade_time'])
            if stamp.tzinfo is None:
                timestamp = stamp.isoformat() + '+08:00'
            else:
                timestamp = stamp.isoformat()
            return quote(market, symbol, row['close'], timestamp, 'tushare', 'A_SHARE_RT')
        return unavailable(market, symbol, 'unsupported_market')
    except urllib.error.HTTPError as exc:
        reason = {401: 'authentication_error', 403: 'entitlement_error', 429: 'rate_limit', 404: 'symbol_not_found'}.get(exc.code, 'provider_error')
        return unavailable(market, symbol, reason)
    except Exception:
        return unavailable(market, symbol, 'network_or_invalid_provider_data')


def fetch_news(feed):
    try:
        root = ET.fromstring(request(feed['url']))
        rows = []
        for item in root.findall('.//item')[:30]:
            title, url, date = item.findtext('title'), item.findtext('link'), item.findtext('pubDate')
            if not title or not url or not url.startswith('https://'):
                continue
            try:
                stamp = parsedate_to_datetime(date).isoformat() if date else None
            except (ValueError, TypeError):
                stamp = None
            rows.append({'id': hashlib.sha256(url.encode()).hexdigest(), 'title': title,
                         'url': url, 'published_at': stamp, 'source': feed['name'], 'market': feed['market'],
                         'status': 'available' if stamp else 'degraded_timestamp_missing'})
        return {'source': feed['name'], 'status': 'available', 'items': rows}
    except Exception:
        return {'source': feed['name'], 'status': 'unavailable', 'items': [], 'reason': 'feed_unavailable'}


def snapshot(config):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [pool.submit(fetch_quote, market, symbol) for market, symbols in config['watchlist'].items() for symbol in symbols]
        news_jobs = [pool.submit(fetch_news, feed) for feed in config.get('news_feeds', [])]
        quotes = [job.result() for job in jobs]
        sources = [job.result() for job in news_jobs]
    news = {item['id']: item for source in sources for item in source['items']}
    return {'version': '0.1.0-dev', 'generated_at': now(), 'quotes': quotes,
            'news': sorted(news.values(), key=lambda item: item['published_at'] or '', reverse=True),
            'news_sources': [{k: v for k, v in source.items() if k != 'items'} for source in sources],
            'data_gaps': [q['symbol'] for q in quotes if q['status'] != 'available'],
            'analysis_status': 'FACTS_ONLY_AI_SYNTHESIS_PENDING', 'refresh_seconds': config['refresh_seconds']}


def serve(config, port):
    state, lock = {'generated_at': None, 'quotes': [], 'news': [], 'data_gaps': [], 'status': 'loading'}, threading.Lock()
    def refresh():
        while True:
            try:
                result = snapshot(config)
                with lock:
                    state.clear(); state.update(result)
            except Exception:
                with lock:
                    state['status'] = 'refresh_failed'
            time.sleep(max(30, config['refresh_seconds']))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/api/snapshot':
                with lock:
                    content = json.dumps(state, ensure_ascii=False).encode()
                content_type = 'application/json; charset=utf-8'
            elif self.path in ('/', '/index.html'):
                content = (ROOT / 'index.html').read_bytes()
                content_type = 'text/html; charset=utf-8'
            else:
                self.send_error(404); return
            self.send_response(200); self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(content)
        def log_message(self, *args):
            pass
    threading.Thread(target=refresh, daemon=True).start()
    print(f'Local dashboard: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(); load_env()
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    if args.once:
        print(json.dumps(snapshot(config), ensure_ascii=False, indent=2))
    else:
        serve(config, args.port)
