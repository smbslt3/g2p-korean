"""소유 계수 명사구와 분류 기준의 독립 합성 대조를 보존한다."""

from dataclasses import asdict

import pytest

from g2p_ko.korean.semantic_policy import SemanticToken, select_senses


# 비공개 실제 입력을 포함하지 않는 독립 구성 대조만 사용한다.
_CASES = [('SC01',
  '물건의 개수를 세었다.',
  [('물건', 'NNG', [['물건', 'NNG']]),
   ('의', 'JKG', [['의', 'JKG']]),
   ('개수', 'NNG', [['개수', 'NNG']]),
   ('를', 'JKO', [['를', 'JKO']]),
   ('세었다', 'VV+EP+EF', [['세', 'VV'], ['었', 'EP'], ['다', 'EF']]),
   ('.', 'SF', [['.', 'SF']])],
  (),
  [(4, 6, 'gaesu.count_quantity')]),
 ('SC02',
  '개수에 따라 등급을 나누었다.',
  [('개수', 'NNG', [['개수', 'NNG']]),
   ('에', 'JKB', [['에', 'JKB']]),
   ('따라', 'VV+EC', [['따르', 'VV'], ['어', 'EC']]),
   ('등급', 'NNG', [['등급', 'NNG']]),
   ('을', 'JKO', [['을', 'JKO']]),
   ('나누었다', 'VV+EP+EF', [['나누', 'VV'], ['었', 'EP'], ['다', 'EF']]),
   ('.', 'SF', [['.', 'SF']])],
  (),
  [(0, 2, None)]),
 ('SC03',
  '건물을 개수한 정도에 따라 등급을 나누었다.',
  [('건물', 'NNG', [['건물', 'NNG']]),
   ('을', 'JKO', [['을', 'JKO']]),
   ('개수', 'NNG', [['개수', 'NNG']]),
   ('한', 'XSV+ETM', [['하', 'XSV'], ['ᆫ', 'ETM']]),
   ('정도', 'NNG', [['정도', 'NNG']]),
   ('에', 'JKB', [['에', 'JKB']]),
   ('따라', 'VV+EC', [['따르', 'VV'], ['어', 'EC']]),
   ('등급', 'NNG', [['등급', 'NNG']]),
   ('을', 'JKO', [['을', 'JKO']]),
   ('나누었다', 'VV+EP+EF', [['나누', 'VV'], ['었', 'EP'], ['다', 'EF']]),
   ('.', 'SF', [['.', 'SF']])],
  (),
  [(4, 6, 'gaesu.renovation')]),
 ('SC04',
  '문제의 개수에 따라 등급 나누었다.',
  [('문제', 'NNG', [['문제', 'NNG']]),
   ('의', 'JKG', [['의', 'JKG']]),
   ('개수', 'NNG', [['개수', 'NNG']]),
   ('에', 'JKB', [['에', 'JKB']]),
   ('따라', 'VV+EC', [['따르', 'VV'], ['어', 'EC']]),
   ('등급', 'NNG', [['등급', 'NNG']]),
   ('나누었다', 'VV+EP+EF', [['나누', 'VV'], ['었', 'EP'], ['다', 'EF']]),
   ('.', 'SF', [['.', 'SF']])],
  (10, 11),
  [(4, 6, None)]),
 ('SC05',
  '개수를 세었다. 개수에 따라 등급을 나누었다.',
  [('개수', 'NNG', [['개수', 'NNG']]),
   ('를', 'JKO', [['를', 'JKO']]),
   ('세었다', 'VV+EP+EF', [['세', 'VV'], ['었', 'EP'], ['다', 'EF']]),
   ('.', 'SF', [['.', 'SF']]),
   ('개수', 'NNG', [['개수', 'NNG']]),
   ('에', 'JKB', [['에', 'JKB']]),
   ('따라', 'VV+EC', [['따르', 'VV'], ['어', 'EC']]),
   ('등급', 'NNG', [['등급', 'NNG']]),
   ('을', 'JKO', [['을', 'JKO']]),
   ('나누었다', 'VV+EP+EF', [['나누', 'VV'], ['었', 'EP'], ['다', 'EF']]),
   ('.', 'SF', [['.', 'SF']])],
  (),
  [(0, 2, 'gaesu.count_quantity'), (9, 11, None)]),
 ('SC06',
  '학교에서 문제의 개수에 따라 등급 나누었다.',
  [('학교', 'NNG', [['학교', 'NNG']]),
   ('에서', 'JKB', [['에서', 'JKB']]),
   ('문제', 'NNG', [['문제', 'NNG']]),
   ('의', 'JKG', [['의', 'JKG']]),
   ('개수', 'NNG', [['개수', 'NNG']]),
   ('에', 'JKB', [['에', 'JKB']]),
   ('따라', 'VV+EC', [['따르', 'VV'], ['어', 'EC']]),
   ('등급', 'NNG', [['등급', 'NNG']]),
   ('나누었다', 'VV+EP+EF', [['나누', 'VV'], ['었', 'EP'], ['다', 'EF']]),
   ('.', 'SF', [['.', 'SF']])],
  (),
  [(9, 11, 'gaesu.count_quantity')])]

@pytest.mark.parametrize("case_id,text,pieces,hard,expected", _CASES, ids=[row[0] for row in _CASES])
def test_quantity_criterion(case_id, text, pieces, hard, expected):
    cursor = 0
    tokens = []
    for form, tag, parts in pieces:
        start = text.index(form, cursor)
        cursor = start + len(form)
        tokens.append(SemanticToken(form, tag, start, cursor, tuple(tuple(pair) for pair in parts)))
    tokens = tuple(tokens)
    before = tuple(asdict(token) for token in tokens)
    selections = select_senses(text, tokens, frozenset(hard))
    assert tuple(asdict(token) for token in tokens) == before
    for start, end, sense in expected:
        matches = [choice for choice in selections
                   if (choice.start, choice.end, choice.spelling) == (start, end, text[start:end])]
        assert len(matches) == 1, case_id
        choice = matches[0]
        assert choice.sense_id == sense, (case_id, choice.reason)
        assert (choice.reason == "selected") == (sense is not None)
        for evidence in choice.evidence:
            assert (evidence.target_start, evidence.target_end) == (start, end)
            assert 0 <= evidence.anchor_start < evidence.anchor_end <= len(text)
            assert not any(min(start, evidence.anchor_start) < cut < max(end, evidence.anchor_end)
                           for cut in hard)
        if sense is not None:
            # 구조 표지만으로 의미 선택의 근거를 대신하지 않는다.
            assert any(evidence.semantic_class == sense.split(".", 1)[1]
                       for evidence in choice.evidence), case_id
