"""Synthetic fixtures only: no raw Eatpl API responses are stored or requested."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import build

AREAS = json.loads((Path(build.ROOT) / 'areas.json').read_text())
JAMSIL = next(a for a in AREAS if a['id'] == 'jamsil')


def item(i, address='서울 송파구 올림픽로 100 (잠실동)', category='한식'):
    return {'merUrl': build.MER_PREFIX + f'mer/web/profile/synthetic-{i}',
            'merNm': f'회귀 테스트 식당 {i}', 'merAddr': address, 'merTpbuzNm': category,
            'srtTime': '1100', 'endTime': '2200', 'allSaleRnk': i + 1, 'ccgSaleRnk': 1}


def urls(board):
    return [s['u'] for s in board['stores']]


class LocalityTests(unittest.TestCase):
    def test_city_and_district_must_both_match(self):
        for addr in ['서울 송파구 신천동 1', '서울특별시 송파구 올림픽로 1', '서울시  송파구  신천동 2']:
            with self.subTest(addr=addr): self.assertTrue(build.in_locality(addr, JAMSIL))
        for addr in ['대구 동구 신천동 1', '경기 시흥시 신천동 1', '서울 강남구 삼성동 1',
                     '서울 송파구청길 1', '부산 강서구 신천동 1', '', None,
                     '대구 동구 신천동 1 (서울 송파구 식당)']:
            with self.subTest(addr=addr): self.assertFalse(build.in_locality(addr, JAMSIL))

    def test_pangyo_requires_seongnam_bundang(self):
        area = next(a for a in AREAS if a['id'] == 'pangyo')
        self.assertTrue(build.in_locality('경기도 성남시 분당구 삼평동 1', area))
        self.assertFalse(build.in_locality('경기 용인시 기흥구 백현동 1', area))

    def test_all_areas_have_explicit_city_and_district_rules(self):
        for area in AREAS:
            self.assertTrue(area['localities'])
            for prefix in area['localities']:
                self.assertGreaterEqual(len(prefix), 2)
                self.assertTrue(prefix[-1].endswith('구'))
        self.assertIn('신천동', JAMSIL['q'])  # Also matches road address + (신천동).

    def test_all_nine_outside_jamsil_results_are_excluded(self):
        bad = [item(100 + i, '대구 동구 동부로30길 100-15 (신천동)') for i in range(6)]
        bad += [item(200 + i, '경기 시흥시 신천동 1') for i in range(2)]
        bad += [item(300, '서울 강남구 삼성동 1')]
        for value in bad: value['allSaleRnk'] = 0.1
        good = [item(i) for i in range(24)]
        self.assertEqual(len(build.pick(bad + good, JAMSIL)), 24)
        self.assertEqual({it['merUrl'] for it in build.pick(bad + good, JAMSIL)}, {it['merUrl'] for it in good})

    def test_compound_dessert_category_excluded_not_restaurant_name(self):
        dessert = item(1, category='아이스크림/요거트/빙수')
        restaurant = item(2); restaurant['merNm'] = '아이스크림 좋아하는 한식집'
        self.assertEqual(build.pick([dessert, restaurant], JAMSIL), [restaurant])

    def test_original_lunch_category_hours_and_url_rules_remain(self):
        okay = item(1)
        late = item(2); late['srtTime'] = '1200'
        cafe = item(3, category='카페')
        external = item(4); external['merUrl'] = 'https://example.com/test'
        self.assertEqual(build.pick([okay, late, cafe, external, okay], JAMSIL), [okay])

    def test_ties_have_deterministic_order(self):
        values = [item(i) for i in range(25)]
        for value in values: value['allSaleRnk'] = value['ccgSaleRnk'] = 1
        self.assertEqual(build.pick(values, JAMSIL), build.pick(list(reversed(values)), JAMSIL))


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.items = [item(i) for i in range(25)]
        self.original = build.make_board(JAMSIL, self.items, '2026-11', '2026-11-01')

    def test_rising_twenty_fifth_store_does_not_change_monthly_board(self):
        changed = copy.deepcopy(self.items)
        changed[24]['allSaleRnk'] = 0.01
        changed[0]['allSaleRnk'] = 80
        result = build.make_board(JAMSIL, changed, '2026-11', '2026-11-02', self.original)
        self.assertEqual(urls(result), urls(self.original))
        self.assertEqual(result['board'], self.original['board'])
        self.assertEqual(next(s['r'] for s in result['stores'] if s['u'] == changed[0]['merUrl']), 80)
        self.assertTrue(all(s['updated'] == '2026-11-02' for s in result['stores']))

    def test_old_deployed_schema_adopts_month_without_reshuffling(self):
        old = copy.deepcopy(self.original); del old['month']
        for store in old['stores']: del store['updated']
        result = build.make_board(JAMSIL, self.items, '2026-11', '2026-11-02', old)
        self.assertEqual(urls(result), urls(old))
        self.assertEqual(result['month'], '2026-11')

    def test_next_month_reselects_and_has_different_identity(self):
        self.items[24]['allSaleRnk'] = 0.01
        result = build.make_board(JAMSIL, self.items, '2026-12', '2026-12-01', self.original)
        self.assertIn(self.items[24]['merUrl'], urls(result))
        self.assertNotEqual(result['board'], self.original['board'])

    def test_missing_capped_search_result_keeps_position_and_old_freshness(self):
        result = build.make_board(JAMSIL, self.items[1:], '2026-11', '2026-11-02', self.original)
        self.assertEqual(urls(result), urls(self.original))
        retained = next(s for s in result['stores'] if s['u'] == self.items[0]['merUrl'])
        self.assertEqual(retained['updated'], '2026-11-01')

    def test_existing_nine_wrong_localities_repaired_without_moving_valid_stores(self):
        bad = [item(100 + i, '대구 동구 신천동 1') for i in range(6)]
        bad += [item(200 + i, '경기 시흥시 신천동 1') for i in range(2)]
        bad += [item(300, '서울 강남구 삼성동 1')]
        previous = copy.deepcopy(self.original)
        previous['stores'][:9] = [build.view(it) for it in bad]
        result = build.make_board(JAMSIL, bad + self.items, '2026-11', '2026-11-02', previous)
        self.assertTrue(all(build.in_locality(s['a'], JAMSIL) for s in result['stores']))
        self.assertEqual(urls(result)[9:], urls(previous)[9:])
        self.assertEqual(len(set(urls(result))), 24)
        self.assertNotEqual(result['board'], previous['board'])

    def test_previously_published_dessert_replaced(self):
        previous = copy.deepcopy(self.original)
        previous['stores'][0]['c'] = '아이스크림/요거트/빙수'
        url = previous['stores'][0]['u']
        for it in self.items:
            if it['merUrl'] == url: it['merTpbuzNm'] = '아이스크림/요거트/빙수'
        result = build.make_board(JAMSIL, self.items, '2026-11', '2026-11-02', previous)
        self.assertNotIn(url, urls(result))
        self.assertEqual(urls(result)[1:], urls(previous)[1:])

    def test_currently_confirmed_non_lunch_store_is_replaced(self):
        url = self.original['stores'][0]['u']
        for it in self.items:
            if it['merUrl'] == url: it['srtTime'] = '1800'
        result = build.make_board(JAMSIL, self.items, '2026-11', '2026-11-02', self.original)
        self.assertNotIn(url, urls(result))

    def test_shortage_fails_instead_of_faking_or_omitting(self):
        with self.assertRaisesRegex(ValueError, 'need 24'):
            build.make_board(JAMSIL, self.items[:23], '2026-11', '2026-11-02')
        old = copy.deepcopy(self.original)
        for s in old['stores']: s['a'] = '대구 동구 신천동 1'
        with self.assertRaisesRegex(ValueError, 'not enough'):
            build.make_board(JAMSIL, self.items[:23], '2026-11', '2026-11-02', old)

    def test_invalid_previous_manifest_fails_closed(self):
        for change in [{'id': 'other'}, {'month': 'nope'}, {'month': '2027-01'}, {'stores': []}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                build.make_board(JAMSIL, self.items, '2026-11', '2026-11-02', {**self.original, **change})


class BuildTests(unittest.TestCase):
    def test_search_schema_errors_are_not_silently_empty_results(self):
        for payload in [{}, {'error': 'unavailable'}, {'items': None}, {'items': {}}, {'items': [None]}]:
            with self.subTest(payload=payload), patch('build.urllib.request.urlopen', return_value=io.StringIO(json.dumps(payload))):
                with self.assertRaises(ValueError): build.fetch('신천동')
        with patch('build.urllib.request.urlopen', return_value=io.StringIO('{"items": []}')):
            self.assertEqual(build.fetch('신천동'), [])

    def test_empty_area_response_cannot_relabel_old_data_as_fresh(self):
        previous = build.make_board(JAMSIL, [item(i) for i in range(24)], '2026-11', '2026-11-01')
        with self.assertRaisesRegex(ValueError, 'no verified lunch data'):
            build.make_board(JAMSIL, [], '2026-11', '2026-11-02', previous)
        # Some valid new results need not include any of the fixed monthly stores.
        retained = build.make_board(JAMSIL, [item(100)], '2026-11', '2026-11-02', previous)
        self.assertEqual(retained['updated'], '2026-11-01')

    def test_unreadable_published_board_fails_not_random_regeneration(self):
        with tempfile.TemporaryDirectory() as td, patch.object(build, 'SITE', td):
            with patch('build.urllib.request.urlopen', side_effect=urllib.error.HTTPError('url', 503, 'unavailable', {}, None)):
                with self.assertRaises(urllib.error.HTTPError): build.load_previous('jamsil')
            with patch('build.urllib.request.urlopen', side_effect=urllib.error.HTTPError('url', 404, 'new area', {}, None)):
                self.assertIsNone(build.load_previous('jamsil'))

    def test_failed_build_preserves_previous_local_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'src').mkdir(); (root / 'src/index.html').write_text('source')
            site = root / 'site'; site.mkdir(); (site / 'keep.txt').write_text('previous output')
            with patch.multiple(build, ROOT=td, SITE=str(site), GAP=0), patch.object(build, 'load_previous', return_value=None), patch.object(build, 'fetch', return_value=[item(1)]):
                with self.assertRaises(ValueError): build.build_site([JAMSIL], '2026-11', '2026-11-02')
            self.assertEqual((site / 'keep.txt').read_text(), 'previous output')

    def test_offline_end_to_end_build_then_stable_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'src').mkdir(); (root / 'src/index.html').write_text('source')
            values = [item(i) for i in range(25)]
            with patch.multiple(build, ROOT=td, SITE=str(root / 'site'), GAP=0, PREVIOUS_SITE=''), patch.object(build, 'fetch', side_effect=lambda _: values):
                build.build_site([JAMSIL], '2026-11', '2026-11-01')
                before = json.loads((root / 'site/data/jamsil.json').read_text())
                values[24]['allSaleRnk'] = 0.01
                build.build_site([JAMSIL], '2026-11', '2026-11-02')
                after = json.loads((root / 'site/data/jamsil.json').read_text())
                self.assertEqual(urls(before), urls(after))
                self.assertEqual(before['board'], after['board'])
                self.assertEqual(len(json.loads((root / 'site/data/areas.json').read_text())['areas']), 1)
                self.assertFalse(list(root.glob('.build-*')))


if __name__ == '__main__':
    unittest.main()
