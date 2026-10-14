import unittest
from unittest.mock import patch
import app

class Contracts(unittest.TestCase):
    def test_stale_never_live(self):
        row=app.quote('us','TEST',100,'2020-01-01T00:00:00Z','test','test')
        self.assertEqual(row['freshness'],'stale')
        self.assertEqual(row['status'],'degraded')
    def test_invalid_price_rejected(self):
        for price in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):app.quote('us','TEST',price,app.now(),'test','test')
    def test_timezone_required(self):
        with self.assertRaises(ValueError):app.quote('us','TEST',10,'2026-01-01T00:00:00','test','test')
    def test_credentials_not_in_output(self):
        with patch.dict(app.os.environ,{'ALPACA_API_KEY':'test-key','ALPACA_SECRET_KEY':'test-secret'}),patch('app.request',side_effect=RuntimeError('test-secret')):
            row=app.fetch_quote('us','TEST')
        self.assertNotIn('test-secret',str(row))
        self.assertEqual(row['status'],'unavailable')

if __name__=='__main__':unittest.main()
