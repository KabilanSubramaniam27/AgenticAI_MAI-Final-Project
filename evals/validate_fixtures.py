"""Offline fixture integrity checks; this does not execute or grade agents."""
import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / 'fixtures'


def read(path):
    return json.loads(path.read_text())


def fixture(ref):
    path = (FIXTURES / ref).resolve()
    assert path.is_relative_to(FIXTURES.resolve()), f'Invalid fixture path: {ref}'
    return read(path)


def check():
    index = fixture('index.json')['cases']
    with (ROOT / 'Golden_Dataset_V1.csv').open(encoding='utf-8-sig', newline='') as f:
        golden = {r['scenario'].split(' — ')[0]: r for r in csv.DictReader(f)}
    assert set(index) == set(golden)
    details = read(ROOT / 'Golden_Dataset_V1_case_details.json')
    counts = Counter()
    for case_id, ref in index.items():
        c = fixture(ref)
        assert c['case_id'] == case_id
        assert c['origin'] == 'synthetic'
        assert c['agent'] == details[case_id]['agent']
        assert details[case_id]['structured_fixture'] == 'fixtures/' + ref
        for key in ('user_input', 'expected_behavior', 'success_criteria', 'failure_edge_cases'):
            assert c[key] == golden[case_id][key], (case_id, key)
        counts[c['agent']] += 1
        inputs = {k: fixture(v) for k, v in c['input_refs'].items()}
        expected = c['expected']
        trip = inputs['trip']
        if 'guides' in inputs:
            guide = inputs['guides']
            archive = fixture(guide['archived_passages_file'])
            for alias in guide['archived_passage_aliases']:
                assert alias in archive
            for passage in guide['synthetic_passages']:
                assert passage['origin'] == 'synthetic'
        if case_id.startswith('TR-PRICE-'):
            n = int(case_id[-3:])
            if n in (1, 2, 3):
                o = inputs['flights']['items'][0]
                total = Decimal(o['amount'])
                if o['basis'] == 'per_adult_round_trip':
                    total *= trip['adults']
                assert total == Decimal(expected['flight_total']), case_id
            if n in (1, 4, 5, 6, 7, 8):
                o = inputs['hotels']['items'][0]
                nights = (date.fromisoformat(o['check_out']) - date.fromisoformat(o['check_in'])).days
                total = Decimal(o['amount'])
                if o['basis'] == 'per_room_per_night':
                    total *= nights * trip['rooms']
                for tax in o.get('excluded_taxes', []):
                    assert tax['basis'] == 'per_adult_per_night'
                    total += Decimal(tax['amount']) * nights * trip['adults']
                assert total == Decimal(expected['hotel_total']), case_id
            if n == 16:
                assert date.fromisoformat(trip['check_out']) < date.fromisoformat(trip['check_in'])
                assert 'reversed_hotel_dates' in c['intentional_invalid_conditions']
        if case_id.startswith('TR-WEATHER-'):
            f = inputs['weather']['forecast']
            policy = inputs['weather']['policy']
            acts = inputs['specialist_results']['itinerary']['activities']
            rows = {r['date']: r for r in f['daily']}
            age = (datetime.fromisoformat(c['as_of']) - datetime.fromisoformat(f['fetched_at'])).total_seconds() / 3600
            usable = (f['status'] == 'ok' and f['kind'] == 'forecast'
                      and f['location']['destination_id'] == trip['destination_id']
                      and 0 <= age <= policy['max_age_hours'])
            actual = {}
            for a in acts:
                rain = rows.get(a['date'], {}).get('precipitation_probability')
                value = None
                if usable and rain is not None and 0 <= rain <= 100 and a['exposure'] != 'unknown':
                    value = bool(a['exposure'] == 'outdoor' and a['rain_sensitive'] and rain >= policy['rain_probability_threshold'])
                actual[a['id']] = value
            assert actual == expected['rain_conflicts'], (case_id, actual, expected)
            if 'heat_conflicts' in expected:
                actual_heat = {a['id']: a['heat_sensitive'] and rows[a['date']]['temperature_max_c'] >= policy['heat_threshold_c'] for a in acts}
                assert actual_heat == expected['heat_conflicts']
            if 'probability_out_of_range' in c['intentional_invalid_conditions']:
                assert any(r['precipitation_probability'] > 100 for r in f['daily'])
        if case_id.startswith('TR-ORCH-'):
            supplied = inputs['specialist_results']
            if supplied.get('costs') and expected.get('total') is not None:
                rate_rows = inputs['currency']['items']
                total = Decimal(0)
                for item in supplied['costs']:
                    amount = Decimal(item['amount'])
                    if item['currency'] != trip['budget']['currency']:
                        rate = next(r for r in rate_rows if r['from'] == item['currency'] and r['to'] == trip['budget']['currency'])
                        amount *= Decimal(rate['rate'])
                    total += amount
                if 'selected_hotel_id' in expected:
                    old = next(i for i in supplied['costs'] if i['category'] == 'lodging')
                    new = next(i for i in supplied['hotel_alternatives'] if i['id'] == expected['selected_hotel_id'])
                    total = total - Decimal(old['amount']) + Decimal(new['amount'])
                assert total == Decimal(expected['total']), case_id
                if 'delta' in expected:
                    assert Decimal(trip['budget']['amount']) - total == Decimal(expected['delta']), case_id
            if expected.get('known_subtotal') is not None:
                subtotal = sum(Decimal(i['amount']) for i in supplied['costs'] if i['amount'] is not None)
                assert subtotal == Decimal(expected['known_subtotal']), case_id
            itinerary = supplied.get('itinerary')
            if itinerary:
                evidence_ids = {e['id'] for e in itinerary['evidence']}
                for day in itinerary['days']:
                    for activity in day['activities']:
                        assert set(activity['evidence_ids']) <= evidence_ids
                assert len(itinerary['days']) == 10
    for passage in fixture('guides/passages.json').values():
        assert hashlib.sha256(passage['text'].encode()).hexdigest() == passage['text_sha256']
    assert all(count == 20 for count in counts.values()) and len(counts) == 4
    for rel, expected_hash in read(ROOT / 'Golden_Dataset_V1_manifest.json')['artifacts_sha256'].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == expected_hash, rel
    print('PASS: 80 linked cases; 20 per agent; references, golden labels, fixture hashes,')
    print('pricing/ledger arithmetic, weather outcomes, deliberate invalid inputs and evidence links.')
    print('Offline fixture checks only. No agents executed; no Chroma access or network calls.')


if __name__ == '__main__':
    check()
