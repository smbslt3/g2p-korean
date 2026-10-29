"""우선순위 토큰 스캔으로 written form을 한국어 발화형으로 바꾼다."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Context, Decimal, localcontext
import re
import unicodedata

from ..english.classify import spell_ascii_letters
from ..errors import ConversionPolicyError, InputValidationError, InternalInvariantError
from ..model import Diagnostic, Handler, Rewrite, RewriteStage, Severity, SourceSpan
from ..scanner import ProtectedRange, scan_protected
from ..unicode import NormalizedText, normalize_nfc, normalize_nfc_text
from .conventional_english import CONVENTIONAL_READINGS
from .english_context import is_standalone_latin_word
from .grammar import (
    _AMBIGUOUS_TOKEN_MESSAGES,
    _BASE_TOKEN_RE,
    _COLON_TIME_RE,
    _CURRENCY_RE,
    _DECIMAL_RE,
    _EMERGENCY_RE,
    _ISO_CURRENCY_RE,
    _KOREAN_SUFFIXES,
    _KOREAN_TIME_RE,
    _NUMBER_HANGUL_UNIT_RE,
    _NUMBER_SUFFIX_RE,
    _NIGHTS_DAYS_RE,
    _ORDINAL_RE,
    _PHONE_RE,
    _POLICIES,
    _QUANTITY_UNIT_RE,
    _RANGE_BOTH_RE,
    _RANGE_RE,
    _SCALED_CURRENCY_RE,
    _SCALED_COMPONENT_RE,
    _SCALED_QUANTITY_RE,
    _SCALED_RANGE_RE,
    _SCALE_POWERS,
    _SEMANTIC_TOKEN_RE,
    _SIMPLE_RENDER_METHODS,
    _SORTED_KOREAN_SUFFIXES,
    _TIME_RANGE_RE,
    _UNSUPPORTED_NUMERIC_KINDS,
)
from .lexicon import CompiledLexicon, _DEFAULT_MAX_VALUE_LENGTH
from .model import NormalizationResult
from .output_policy import (
    OUTPUT_POLICIES,
    finish_tts_output,
    is_tts_text,
    punctuation_output,
    prepare_tts_input,
    render_structure,
    render_tts_semantic,
    render_unknown_latin,
    tts_semantic_matches,
)
from ..number_reader import NumberReadingRun
from .numbers import (
    NumberFormatError,
    has_ambiguous_leading_zero,
    parse_number,
    read_digitwise,
    read_history_digits,
    read_native_or_sino,
    read_native_standalone_or_sino,
    read_phone_digits,
    read_sino,
)
from .policy import (
    _Rendered,
    ambiguous,
    is_permitted_whitespace,
    is_unsafe_attached_character,
    raise_ambiguous,
    record_rendered,
    unsupported_character,
)
from .renderers import (
    SIMPLE_RENDERERS,
    expected_match,
    format_quantity,
    may_be_thousands_separator,
    render_date,
    render_fraction,
    render_indefinite_unit,
    render_number,
    render_standalone_unit_symbol,
    render_unit_per,
    scale_decimal,
)
from .tts_recovery import recover_tts_quantity
from .units import (
    _ALL_UNITS,
    _CONTEXT_INDEPENDENT_NATIVE_COUNTERS,
    _CONTEXT_INDEPENDENT_SINO_UNITS,
    _CURRENCIES,
    _CURRENCY_UNIT_WORDS,
    _ISO_CURRENCIES,
    _JAMO_NAMES,
    _NATIVE_COUNTERS,
    _SPEED_UNIT_READINGS,
)


def _is_plain_korean_text(text: str) -> bool:
    """변환·진단 후보가 전혀 없는 완성형 한글 문장을 빠르게 확인한다."""

    return all(
        "가" <= character <= "힣"
        or is_permitted_whitespace(character)
        or (
            unicodedata.category(character).startswith("P")
            and character not in "%％"
        )
        for character in text
    )


@dataclass(frozen=True, slots=True)
class _TokenMatch:
    """기본 규칙과 사용자 사전 매치를 같은 방식으로 순회하기 위한 뷰다."""

    start: int
    end: int
    kind: str
    token: str


@dataclass(frozen=True, slots=True)
class _TextOnlyNormalized:
    """문자열 API에서 code point별 원문 span 할당을 생략하는 뷰다."""

    text: str

    def source_span(self, start: int, end: int) -> SourceSpan:
        """문자열 전용 경로에서는 호출되지 않아야 한다."""

        raise InternalInvariantError(f"문자열 전용 정규화에는 원문 span이 없습니다: {start}:{end}")


@dataclass(slots=True)
class _RunState:
    """한 번의 변환에서 출력 예산과 진단·완료 상태를 함께 관리한다."""

    max_output_length: int
    chunks: list[str] = field(default_factory=list)
    rewrites: list[Rewrite] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    unresolved: bool = False
    output_length: int = 0
    character_spans: list[SourceSpan] | None = None

    def append(self, chunk: str, *, spans: Iterable[SourceSpan] | None = None) -> None:
        next_length = self.output_length + len(chunk)
        if next_length > self.max_output_length:
            raise InputValidationError(
                f"정규화 출력이 최대 길이 {self.max_output_length}를 초과했습니다."
            )
        self.output_length = next_length
        self.chunks.append(chunk)
        if self.character_spans is not None:
            if spans is None:
                raise InternalInvariantError("TTS 출력 조각에는 원문 문자 span이 필요합니다.")
            chunk_spans = list(spans)
            if len(chunk_spans) != len(chunk):
                raise InternalInvariantError("TTS 출력 조각과 원문 문자 span 수가 다릅니다.")
            self.character_spans.extend(chunk_spans)

    def note_unresolved(self, value: bool) -> None:
        self.unresolved |= value

    def result(self, source: str) -> NormalizationResult:
        text = "".join(self.chunks)
        if self.character_spans is not None:
            text, allowed = finish_tts_output(
                source, text, self.character_spans,
                self.rewrites, self.diagnostics,
            )
            self.note_unresolved(not allowed)
            if len(text) > self.max_output_length:
                raise InputValidationError(
                    f"정규화 출력이 최대 길이 {self.max_output_length}를 초과했습니다."
                )
        return NormalizationResult(
            source,
            text,
            tuple(self.rewrites),
            tuple(self.diagnostics),
            not self.unresolved,
        )


class KoreanTTSNormalizer:
    """문장 구조를 보존하며 비표준 표기를 한국어 발화형으로 바꾼다.

    숫자 형식과 단위는 규칙으로 읽는다. ``number_reader``를 지정하면
    별도 HF 모델이 애매한 숫자의 문맥을 판단한다. 모델은 호출자가 준비하며
    기본 생성자에서는 네트워크나 숫자 모델에 접근하지 않는다.

    기존 호출의 ``output_policy="preserve"``는 문장 구조와 보호 토큰을 보존한다.
    실제 TTS 문자열에는 ``output_policy="tts"`` 또는 ``normalize_tts``를 쓴다.
    이 경로는 완성형 한글·공백·``,.!?``만 반환하고 미해결 의미가 남으면 오류를
    낸다. 상세 ``convert_tts``는 실패한 중간 문자열과 진단도 반환한다.
    """

    def __init__(
        self,
        *,
        lexicon: Mapping[str, str] | None = None,
        on_ambiguous: str = "warn",
        max_length: int = 10_000,
        max_output_length: int | None = None,
        output_policy: str = "preserve",
        number_reader: object | None = None,
    ) -> None:
        if not isinstance(output_policy, str) or output_policy not in OUTPUT_POLICIES:
            raise InputValidationError("output_policy는 preserve, tts 중 하나여야 합니다.")
        if not isinstance(on_ambiguous, str) or on_ambiguous not in _POLICIES:
            raise InputValidationError("on_ambiguous는 preserve, warn, error 중 하나여야 합니다.")
        if not isinstance(max_length, int) or isinstance(max_length, bool) or max_length <= 0:
            raise InputValidationError("max_length는 양의 정수여야 합니다.")
        if max_output_length is None:
            max_output_length = max_length * 16
        if (
            not isinstance(max_output_length, int)
            or isinstance(max_output_length, bool)
            or max_output_length <= 0
        ):
            raise InputValidationError("max_output_length는 양의 정수여야 합니다.")
        # 사전 값도 기본 규칙으로 한 번 읽어 반복 호출의 결과를 같게 만든다.
        self._on_ambiguous = "preserve"
        # 기존 사전 값 정규화의 계약은 출력 정책을 바꾸더라도 유지한다.
        self._output_policy = "preserve"
        # 사전 자기검증이 판별기 없이 결정적으로 돌도록 마지막에 켠다.
        self._number_reader: object | None = None
        # 사전 값은 사용자 입력 제한과 별개인 사전 값 길이 제한으로 검증한다.
        self._max_length = _DEFAULT_MAX_VALUE_LENGTH
        self._max_output_length = max_output_length
        self._lexicon: CompiledLexicon | None = None
        if lexicon is not None:
            compiled_lexicon = CompiledLexicon(
                lexicon,
                base_normalize=self.normalize,
            )
            if compiled_lexicon:
                self._lexicon = compiled_lexicon
                for key, value in compiled_lexicon.items():
                    validation = self.convert(value)
                    if validation.normalized_text != value or not validation.complete:
                        raise InputValidationError(
                            "lexicon 값은 한 번의 변환 뒤 완결된 발화형이어야 "
                            f"합니다: {key!r}"
                        )
        self._max_length = max_length
        self._on_ambiguous = on_ambiguous
        self._output_policy = output_policy
        if number_reader is not None and not callable(getattr(number_reader, "new_run", None)):
            raise InputValidationError("number_reader는 new_run 메서드를 제공해야 합니다.")
        self._number_reader = number_reader

    def __call__(self, text: str) -> str:
        """상세 객체를 만들지 않고 정규화 문자열만 반환한다."""

        return self.normalize(text)

    def normalize(self, text: str) -> str:
        """정규화 문자열만 반환하는 빠른 경로다."""

        result = self._run(text, trace=False)
        return self._tts_string(result) if self._output_policy == "tts" else result.normalized_text

    def convert(self, text: str) -> NormalizationResult:
        """정규화 문자열과 rewrite·diagnostic을 모두 반환한다."""

        return self._run(text, trace=True)

    def normalize_tts(self, text: str) -> str:
        """성공한 한글 TTS 문자열만 반환하고 미해결 입력은 오류로 보고한다."""

        return self._tts_string(self._run(text, trace=True, output_policy="tts"))

    def convert_tts(self, text: str) -> NormalizationResult:
        """엄격한 TTS 출력 계약을 적용한 결과와 원문 좌표 진단을 반환한다."""

        return self._run(text, trace=True, output_policy="tts")

    @staticmethod
    def _tts_string(result: NormalizationResult) -> str:
        if not result.complete or not is_tts_text(result.normalized_text):
            diagnostic = result.diagnostics[0] if result.diagnostics else None
            raise ConversionPolicyError(
                diagnostic.code if diagnostic is not None else "incomplete_tts_normalization",
                diagnostic.message if diagnostic is not None else "TTS 읽기를 손실 없이 확정할 수 없습니다.",
                source_span=(diagnostic.source_spans[0] if diagnostic is not None and diagnostic.source_spans else None),
                rule_id=diagnostic.rule_id if diagnostic is not None else "normalizer.tts.output_contract.v1",
            )
        return result.normalized_text

    def normalize_many(self, texts: Iterable[str]) -> Iterator[str]:
        """입력을 미리 모으지 않고 문자열을 순서대로 정규화한다."""

        if isinstance(texts, (str, bytes)) or not isinstance(texts, Iterable):
            raise InputValidationError("texts는 문자열이 아닌 문자열 iterable이어야 합니다.")
        return map(self.normalize, texts)

    def convert_many(self, texts: Iterable[str]) -> Iterator[NormalizationResult]:
        """입력을 미리 모으지 않고 상세 결과를 순서대로 변환한다."""

        if isinstance(texts, (str, bytes)) or not isinstance(texts, Iterable):
            raise InputValidationError("texts는 문자열이 아닌 문자열 iterable이어야 합니다.")
        return map(self.convert, texts)

    def _run(self, source: str, *, trace: bool, output_policy: str | None = None) -> NormalizationResult:
        tts = (self._output_policy if output_policy is None else output_policy) == "tts"
        # 엄격한 문자열 경로도 실패 원인과 장식 삭제의 정확한 원문 좌표를 만든다.
        trace = trace or tts
        normalized: NormalizedText | _TextOnlyNormalized
        if trace or self._on_ambiguous == "error":
            normalized = normalize_nfc(source, max_length=self._max_length)
            initial_rewrites = normalized.rewrites if trace else ()
        else:
            normalized = _TextOnlyNormalized(
                normalize_nfc_text(source, max_length=self._max_length),
            )
            initial_rewrites = ()
        preparation_diagnostics: tuple[Diagnostic, ...] = ()
        if tts:
            assert isinstance(normalized, NormalizedText)
            protected = scan_protected(normalized.text)
            # 사용자가 명시한 사전 키의 장식은 삭제하지 않고 기존 사전 매칭에 맡긴다.
            lexical = (() if self._lexicon is None else tuple(
                ProtectedRange(match.start, match.end, "user_lexicon")
                for match in self._lexicon.iter_matches(normalized.text)
            ))
            normalized, preparation_diagnostics = prepare_tts_input(normalized, (*protected, *lexical))
            initial_rewrites = normalized.rewrites
        state = _RunState(
            self._max_output_length, rewrites=list(initial_rewrites),
            character_spans=[] if tts else None,
            diagnostics=list(preparation_diagnostics), unresolved=bool(preparation_diagnostics),
        )
        if not normalized.text:
            return self._finish_run(state, source, tts=tts)
        if (
            self._lexicon is None and _is_plain_korean_text(normalized.text)
        ):
            self._append_source(state, normalized, 0, len(normalized.text))
            return self._finish_run(state, source, tts=tts)

        protected = scan_protected(normalized.text)
        cursor = 0
        # 판별 문맥은 호출마다 새로 만들어 같은 인스턴스를 여러 스레드가
        # 동시에 써도 분석 결과가 섞이지 않게 한다.
        number_run = (
            self._number_reader.new_run(normalized.text)
            if self._number_reader is not None
            else None
        )
        for item in protected:
            self._normalize_range(
                normalized, cursor, item.start,
                trace=trace, state=state, number_run=number_run,
                tts=tts,
            )
            if tts:
                token = normalized.text[item.start:item.end]
                rendered = render_structure(token, item.kind)
                span = normalized.source_span(item.start, item.end)
                state.append(rendered.text, spans=[span] * len(rendered.text))
                state.note_unresolved(rendered.unresolved)
                record_rendered(rendered, token, span, state.rewrites, state.diagnostics,
                                on_ambiguous=self._on_ambiguous)
            else:
                self._append_source(state, normalized, item.start, item.end)
            cursor = item.end
        self._normalize_range(
            normalized, cursor, len(normalized.text),
            trace=trace, state=state, number_run=number_run,
            tts=tts,
        )
        return self._finish_run(state, source, tts=tts)

    def _finish_run(self, state: _RunState, source: str, *, tts: bool) -> NormalizationResult:
        result = state.result(source)
        # 빠른 경로와 최종 허용 문자 검사에도 명시적인 오류 정책을 적용한다.
        if tts and self._on_ambiguous == "error" and not result.complete:
            self._tts_string(result)
        return result

    def _normalize_range(
        self,
        normalized: NormalizedText | _TextOnlyNormalized,
        start: int,
        end: int,
        *,
        trace: bool,
        state: _RunState,
        number_run: NumberReadingRun | None = None,
        tts: bool = False,
    ) -> None:
        if start >= end:
            return
        cursor = start
        for match in self._iter_token_matches(normalized.text, start, end, tts=tts):
            if match.start < cursor:
                continue
            self._append_source(state, normalized, cursor, match.start)
            state.note_unresolved(self._inspect_unmatched(
                normalized,
                cursor,
                match.start,
                trace=trace,
                rewrites=state.rewrites,
                diagnostics=state.diagnostics,
                tts=tts,
            ))
            token_end = match.end
            while token_end < end and is_unsafe_attached_character(
                normalized.text[token_end]
            ):
                token_end += 1
            if token_end != match.end:
                token = normalized.text[match.start:token_end]
                rendered = ambiguous(
                    token,
                    "unsupported_script",
                    "토큰에 결합할 수 없는 문자가 붙어 있어 원문을 보존합니다.",
                )
            else:
                token = match.token
                if tts and match.kind in {"tts_identifier", "tts_ordinal"}:
                    rendered = render_tts_semantic(token, match.kind)
                elif tts and match.kind in {"latin", "acronym"} and token.upper() in CONVENTIONAL_READINGS:
                    # 보호 구간은 이미 분리했으며 독립 단어의 대소문자 변형만 허용한다.
                    if is_standalone_latin_word(normalized.text, match.start, match.end, protected=()):
                        rendered = _Rendered(CONVENTIONAL_READINGS[token.upper()], Handler.ENGLISH,
                                             "normalizer.tts.english_conventional.v1")
                    else:
                        # 연결 토큰은 관용 읽기를 일부 적용하지 않고 기존 철자 읽기로 보낸다.
                        rendered = render_unknown_latin(token)
                elif tts and match.kind in {"latin", "ambiguous_latin_hyphen"}:
                    rendered = render_unknown_latin(token)
                else:
                    rendered = self._render(
                        match.kind,
                        token,
                        previous=normalized.text[match.start - 1:match.start],
                        number_run=number_run,
                        start=match.start,
                    )
                if tts and rendered.handler is Handler.PROTECTED and not rendered.unresolved:
                    rendered = render_structure(token, match.kind)
            if tts and rendered.unresolved and rendered.diagnostic_code == "ambiguous_numeric":
                rendered = recover_tts_quantity(
                    token, rendered, previous=normalized.text[match.start - 1:match.start],
                    following=normalized.text[token_end:end],
                )
            span = normalized.source_span(match.start, token_end) if tts else None
            state.append(rendered.text, spans=[span] * len(rendered.text) if span is not None else None)
            state.note_unresolved(rendered.unresolved)
            if trace:
                span = normalized.source_span(match.start, token_end)
                record_rendered(
                    rendered, token, span, state.rewrites, state.diagnostics,
                    on_ambiguous=self._on_ambiguous,
                )
                if number_run is not None:
                    failure = number_run.take_failure()
                    if failure is not None:
                        # 판별 실패는 규칙 경로로 폴백하므로 완결성에는 영향이 없다.
                        state.diagnostics.append(
                            Diagnostic(
                                failure[0],
                                failure[1],
                                Severity.WARNING,
                                (span,),
                                None,
                                RewriteStage.VERBALIZATION,
                            )
                        )
            elif rendered.unresolved and self._on_ambiguous == "error":
                span = normalized.source_span(match.start, token_end)
                raise_ambiguous(rendered, span)
            cursor = token_end
        self._append_source(state, normalized, cursor, end)
        state.note_unresolved(self._inspect_unmatched(
            normalized,
            cursor,
            end,
            trace=trace,
            rewrites=state.rewrites,
            diagnostics=state.diagnostics,
            tts=tts,
        ))

    @staticmethod
    def _append_source(
        state: _RunState,
        normalized: NormalizedText | _TextOnlyNormalized,
        start: int,
        end: int,
    ) -> None:
        spans = None
        if state.character_spans is not None:
            if not isinstance(normalized, NormalizedText):
                raise InternalInvariantError("TTS 정책에는 원문 span 정규화가 필요합니다.")
            spans = normalized.character_spans[start:end]
        state.append(normalized.text[start:end], spans=spans)

    def _iter_token_matches(
        self,
        text: str,
        start: int,
        end: int,
        *,
        tts: bool = False,
    ) -> Iterator[_TokenMatch]:
        """기본 규칙과 trie 사전을 시작점 우선, 동률이면 사전 우선으로 합친다."""

        def base_matches() -> Iterator[_TokenMatch]:
            matches = []
            for match in _BASE_TOKEN_RE.finditer(text, start, end):
                kind = match.lastgroup
                if kind is None:
                    raise InternalInvariantError("토큰 정규식에 이름이 없습니다.")
                candidate = _TokenMatch(match.start(), match.end(), kind, match.group(0))
                if not tts:
                    yield candidate
                else:
                    matches.append(candidate)
            if tts:
                matches.extend(_TokenMatch(*item) for item in tts_semantic_matches(text, start, end))
                # 같은 시작점에서는 TTS의 명시적 구조가 기존 미해석 보호 토큰보다 우선한다.
                yield from sorted(matches, key=lambda m: (m.start, not m.kind.startswith("tts_"), -m.end))

        lexicon = self._lexicon
        lexicon_matches = (
            iter(())
            if lexicon is None
            else (
                _TokenMatch(item.start, item.end, "user_lexicon", item.key)
                for item in lexicon.iter_matches(text, start=start, end=end)
            )
        )
        base_iterator = base_matches()
        lexicon_iterator = iter(lexicon_matches)
        base = next(base_iterator, None)
        lexical = next(lexicon_iterator, None)
        occupied_until = start
        while base is not None or lexical is not None:
            use_lexicon = lexical is not None and (
                base is None or lexical.start <= base.start
            )
            if use_lexicon:
                candidate = lexical
                lexical = next(lexicon_iterator, None)
            else:
                candidate = base
                base = next(base_iterator, None)
            assert candidate is not None
            if candidate.start < occupied_until:
                continue
            yield candidate
            occupied_until = candidate.end

    def _inspect_unmatched(
        self,
        normalized: NormalizedText | _TextOnlyNormalized,
        start: int,
        end: int,
        *,
        trace: bool,
        rewrites: list[Rewrite],
        diagnostics: list[Diagnostic],
        tts: bool = False,
    ) -> bool:
        """규칙에 잡히지 않은 문자 중 TTS가 해석할 수 없는 범위를 진단한다."""

        unresolved = False
        cursor = start
        while cursor < end:
            if tts and punctuation_output(normalized.text[cursor]) is not None:
                cursor += 1
                continue
            classification = unsupported_character(normalized.text[cursor])
            if classification is None:
                cursor += 1
                continue
            code, message = classification
            token_end = cursor + 1
            while (
                token_end < end
                and unsupported_character(normalized.text[token_end]) == classification
            ):
                token_end += 1
            token = normalized.text[cursor:token_end]
            rendered = ambiguous(token, code, message)
            unresolved = True
            if trace:
                span = normalized.source_span(cursor, token_end)
                record_rendered(
                    rendered, token, span, rewrites, diagnostics,
                    on_ambiguous=self._on_ambiguous,
                )
            elif self._on_ambiguous == "error":
                span = normalized.source_span(cursor, token_end)
                raise_ambiguous(rendered, span)
            cursor = token_end
        return unresolved

    def _render(
        self,
        kind: str,
        token: str,
        *,
        previous: str = "",
        number_run: NumberReadingRun | None = None,
        start: int | None = None,
        context_end: int | None = None,
    ) -> _Rendered:
        ambiguity = _AMBIGUOUS_TOKEN_MESSAGES.get(kind)
        if ambiguity is not None:
            return ambiguous(token, *ambiguity)
        if kind in _UNSUPPORTED_NUMERIC_KINDS:
            return ambiguous(
                token,
                "ambiguous_numeric",
                "지원하지 않는 숫자 구조는 원문을 보존합니다.",
            )
        pure_renderer = SIMPLE_RENDERERS.get(kind)
        if pure_renderer is not None:
            return pure_renderer(token)
        simple_method = _SIMPLE_RENDER_METHODS.get(kind)
        if simple_method is not None:
            return getattr(self, simple_method)(token)
        if kind == "semantic_cluster":
            return self._render_semantic_cluster(token, number_run=number_run, start=start)
        if kind == "scaled_quantity":
            return self._render_scaled_quantity(token)
        if kind == "nights_days":
            return self._render_nights_days(token)
        if kind in {"range", "range_both", "scaled_range"}:
            return self._render_range(token, kind=kind)
        if kind in {"version", "filename"}:
            return _Rendered(token, Handler.PROTECTED, f"protected.{kind}")
        if kind == "ipv4":
            if all(int(octet) <= 255 for octet in token.split(".")):
                return _Rendered(token, Handler.PROTECTED, "protected.ipv4")
            return ambiguous(token, "ambiguous_numeric", "유효하지 않은 IPv4 주소입니다.")
        if kind == "user_lexicon":
            if self._lexicon is None:
                raise InternalInvariantError("사용자 사전 매치에 컴파일된 사전이 없습니다.")
            return _Rendered(self._lexicon[token], Handler.KOREAN, "normalizer.user_lexicon.v1")
        if kind in {"date", "korean_date"}:
            return render_date(token, korean=kind == "korean_date")
        if kind == "numbered_item":
            return self._render_number_hangul_unit(token, force_sino=True)
        if kind == "numeric_guard":
            if re.search(r"[A-Za-z]", token):
                return ambiguous(
                    token,
                    "ambiguous_identifier",
                    "영숫자 식별자의 의도한 읽기를 확정할 수 없습니다.",
                )
            return ambiguous(
                token,
                "ambiguous_numeric",
                "지원하지 않는 숫자 구조는 원문을 보존합니다.",
            )
        if kind == "number_hangul_unit":
            return self._render_number_hangul_unit(
                token,
                force_sino=previous == "제",
                number_run=number_run,
                start=start,
                context_end=context_end,
            )
        if kind in {"fraction_unit", "number_unit", "quantity_unit"}:
            return self._render_quantity_unit(
                token,
                force_sino=previous == "제",
                number_run=number_run,
                start=start,
                context_end=(
                    context_end
                    if context_end is not None
                    else None if start is None else start + len(token)
                ),
            )
        if kind == "indefinite_unit":
            return render_indefinite_unit(token)
        if kind == "unit_per":
            return render_unit_per(token)
        if kind == "standalone_unit_symbol":
            return render_standalone_unit_symbol(token)
        if kind == "number_suffix":
            match = expected_match(_NUMBER_SUFFIX_RE, token)
            number = match.group("number")
            rendered = render_number(
                number,
                rule_id="normalizer.number.sino.v1",
                original=token,
            )
            if rendered.unresolved:
                return rendered
            rendered = self._apply_bare_number_context(
                rendered,
                number,
                number_run,
                None if start is None else start + match.start("number"),
                None if start is None else start + len(token),
            )
            return _Rendered(
                rendered.text + match.group("suffix"),
                rendered.handler,
                rendered.rule_id,
            )
        if kind == "decimal":
            try:
                parsed = parse_number(token)
            except NumberFormatError:
                return ambiguous(token, "ambiguous_numeric", "소수를 손실 없이 읽을 수 없습니다.")
            if len(parsed.integer) > 10:
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "긴 숫자가 식별번호인지 수량인지 확정할 수 없습니다.",
                )
            return render_number(token, rule_id="normalizer.number.sino.v1")
        if kind == "number":
            rendered = render_number(token, rule_id="normalizer.number.sino.v1")
            if rendered.unresolved:
                return rendered
            return self._apply_bare_number_context(
                rendered,
                token,
                number_run,
                start,
                (
                    context_end
                    if context_end is not None
                    else None if start is None else start + len(token)
                ),
            )
        if kind == "number_punctuation":
            rendered = render_number(
                token[:-1],
                rule_id="normalizer.number.sino.v1",
                original=token,
            )
            if rendered.unresolved:
                return rendered
            rendered = self._apply_bare_number_context(
                rendered,
                token[:-1],
                number_run,
                start,
                None if start is None else start + len(token) - 1,
            )
            return _Rendered(
                rendered.text + token[-1],
                rendered.handler,
                rendered.rule_id,
            )
        if kind == "jamo":
            return _Rendered(_JAMO_NAMES[token], Handler.KOREAN, "normalizer.jamo_name.v1")
        raise InternalInvariantError(f"알 수 없는 normalizer 토큰입니다: {kind}")

    def _render_phone(self, token: str) -> _Rendered:
        match = expected_match(_PHONE_RE, token)
        number = match.group("number")
        groups = re.findall(r"[0-9]+", number)
        prefix = "플러스 " if number.startswith("+") else ""
        return _Rendered(
            prefix
            + " ".join(read_phone_digits(item) for item in groups)
            + (match.group("suffix") or ""),
            Handler.NUMERIC,
            "normalizer.phone.v1",
        )

    def _render_emergency(self, token: str) -> _Rendered:
        match = expected_match(_EMERGENCY_RE, token)
        return _Rendered(
            read_phone_digits(match.group("number")) + (match.group("suffix") or ""),
            Handler.NUMERIC,
            "normalizer.emergency_number.v1",
        )

    def _render_ordinal(self, token: str) -> _Rendered:
        match = expected_match(_ORDINAL_RE, token)
        rendered = self._render_number_hangul_unit(match.group("body"), force_sino=True)
        if rendered.unresolved:
            return ambiguous(token, "ambiguous_numeric", "서수 표현을 손실 없이 읽을 수 없습니다.")
        return _Rendered(
            "제 " + rendered.text,
            Handler.NUMERIC,
            "normalizer.ordinal_context.v1",
        )

    def _render_history(self, token: str) -> _Rendered:
        numeric_match = re.match(r"[0-9]{1,2}[.·][0-9]{1,2}", token)
        if numeric_match is None:
            return ambiguous(token, "ambiguous_numeric", "역사 날짜를 분리할 수 없습니다.")
        try:
            spoken = read_history_digits(numeric_match.group(0))
        except NumberFormatError:
            return ambiguous(
                token,
                "ambiguous_numeric",
                "역사 날짜를 손실 없이 읽을 수 없습니다.",
            )
        return _Rendered(
            spoken + token[numeric_match.end() :],
            Handler.NUMERIC,
            "normalizer.historical_date.v1",
        )

    def _render_currency(self, token: str) -> _Rendered:
        match = expected_match(_CURRENCY_RE, token)
        unit = _CURRENCIES[match.group("symbol")]
        spoken_unit = match.group("spoken_unit")
        if spoken_unit is not None and spoken_unit != unit:
            return ambiguous(token, "ambiguous_numeric", "통화 기호와 단위가 서로 다릅니다.")
        return render_number(
            match.group("number"),
            suffix=unit,
            rule_id="normalizer.currency_prefix.v1",
            original=token,
        )

    def _render_acronym(self, token: str) -> _Rendered:
        reading = CONVENTIONAL_READINGS.get(token)
        if reading is not None:
            return _Rendered(
                reading,
                Handler.ENGLISH,
                "normalizer.english_acronym_exception.v1",
            )
        return _Rendered(
            self._read_letters(token),
            Handler.ENGLISH,
            "normalizer.english_initialism.v1",
        )

    def _render_semantic_cluster(
        self,
        token: str,
        *,
        number_run: NumberReadingRun | None = None,
        start: int | None = None,
    ) -> _Rendered:
        """공백 없는 숫자 인접 토큰을 전체 검증해 부분 변환을 막는다."""

        if not re.search(r"[0-9]", token):
            if any(character.isnumeric() for character in token) and not all(
                character in "²³⁴" for character in token
            ):
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "ASCII가 아닌 숫자의 읽기를 확정할 수 없습니다.",
                )
            return ambiguous(
                token,
                "unsupported_symbol",
                "발화 규칙이 없는 의미 기호는 원문을 보존합니다.",
            )
        punctuation = token[-1] if token[-1:] in {".", ","} else ""
        body = token[:-1] if punctuation else token
        # 조사 후보를 떼어 내며 재분류하더라도 문맥 경계는 원래 토큰의 끝으로
        # 유지한다. 그래야 다른 경로와 같은 자질(꼬리=조사, 다음=뒷낱말)을 본다.
        body_end = None if start is None else start + len(body)
        rendered = self._classify_semantic_cluster(
            body, number_run=number_run, start=start, context_end=body_end
        )
        unresolved = rendered
        suffix = ""
        if rendered.unresolved:
            for candidate in _SORTED_KOREAN_SUFFIXES:
                if not body.endswith(candidate) or len(body) == len(candidate):
                    continue
                remainder = body[: -len(candidate)]
                if candidate == "만" and _DECIMAL_RE.fullmatch(remainder):
                    # `3.000만 원`의 만은 배율일 수 있어 소수+조사로 읽지 않는다.
                    continue
                candidate_rendered = self._classify_semantic_cluster(
                    remainder, number_run=number_run, start=start, context_end=body_end
                )
                if candidate_rendered.unresolved:
                    if candidate_rendered.diagnostic_code != "ambiguous_numeric":
                        unresolved = candidate_rendered
                    continue
                rendered = candidate_rendered
                suffix = candidate
                break
        if rendered.unresolved:
            return ambiguous(
                token,
                unresolved.diagnostic_code or "ambiguous_numeric",
                unresolved.diagnostic_message or "지원하지 않는 숫자 구조는 원문을 보존합니다.",
            )
        return _Rendered(
            rendered.text + suffix + punctuation,
            rendered.handler,
            rendered.rule_id,
        )

    def _classify_semantic_cluster(
        self,
        token: str,
        *,
        number_run: NumberReadingRun | None = None,
        start: int | None = None,
        context_end: int | None = None,
    ) -> _Rendered:
        """공백 없는 숫자 후보 하나를 정확히 한 규칙으로 분류한다.

        ``context_end``는 조사 후보를 떼기 전 토큰의 끝이다. 판별 자질이
        다른 경로와 같은 문맥을 보게 하려고 분류 대상 길이와 따로 받는다.
        """

        if context_end is None and start is not None:
            context_end = start + len(token)

        match = _SEMANTIC_TOKEN_RE.fullmatch(token)
        if match is not None:
            kind = match.lastgroup
            if kind is None:
                raise InternalInvariantError("숫자 결합 토큰 규칙에 이름이 없습니다.")
            return self._render(
                kind,
                token,
                number_run=number_run,
                start=start,
                context_end=context_end,
            )
        if re.fullmatch(r"[+\-−]?[0-9][0-9,]*(?:\.[0-9]+)?[eE][+\-]?[0-9]+", token):
            code = "ambiguous_numeric"
            message = "지원하지 않는 과학적 표기법은 원문을 보존합니다."
        elif re.search(r"[A-Za-z]", token):
            code = "ambiguous_identifier"
            message = "영숫자 식별자의 의도한 읽기를 확정할 수 없습니다."
        else:
            code = "ambiguous_numeric"
            message = "지원하지 않는 숫자 구조는 원문을 보존합니다."
        return ambiguous(token, code, message)

    def _render_time(self, token: str) -> _Rendered:
        """12시간·24시간 표기를 값 검증 뒤 시·분·초 발화형으로 바꾼다."""

        match = _COLON_TIME_RE.fullmatch(token) or _KOREAN_TIME_RE.fullmatch(token)
        if match is None:
            return ambiguous(token, "ambiguous_numeric", "시간 구성요소를 분리할 수 없습니다.")
        period = match.group("period")
        hour = int(match.group("hour"))
        minute_surface = match.group("minute")
        second_surface = match.group("second")
        minute = int(minute_surface) if minute_surface is not None else None
        second = int(second_surface) if second_surface is not None else None
        valid_hour = 1 <= hour <= 12 if period is not None else 0 <= hour <= 24
        valid_24 = hour != 24 or ((minute or 0) == 0 and (second or 0) == 0)
        if (
            not valid_hour
            or not valid_24
            or (minute is not None and not 0 <= minute <= 59)
            or (second is not None and not 0 <= second <= 59)
        ):
            return ambiguous(token, "ambiguous_numeric", "유효하지 않은 시각 표기입니다.")

        if period is not None or 1 <= hour <= 12:
            spoken_hour = read_native_or_sino(str(hour))
        else:
            spoken_hour = read_sino(str(hour))
        parts = [f"{spoken_hour} 시"]
        if minute is not None:
            parts.append(f"{read_sino(str(minute))} 분")
        if second is not None:
            parts.append(f"{read_sino(str(second))} 초")
        prefix = f"{period} " if period is not None else ""
        suffix = match.group("suffix") or ""
        return _Rendered(
            prefix + " ".join(parts) + suffix,
            Handler.NUMERIC,
            "normalizer.clock_time.v1",
        )

    def _render_time_range(self, token: str) -> _Rendered:
        """양쪽 시각이 완전히 쓰인 범위만 `에서`로 연결한다."""

        match = _TIME_RANGE_RE.fullmatch(token)
        if match is None:
            return ambiguous(token, "ambiguous_numeric", "시각 범위를 분리할 수 없습니다.")
        left_token = match.group("left")
        right_token = match.group("right")
        left_match = _COLON_TIME_RE.fullmatch(left_token) or _KOREAN_TIME_RE.fullmatch(left_token)
        if left_match is None or left_match.group("suffix") is not None:
            return ambiguous(
                token,
                "ambiguous_numeric",
                "범위 중간에 조사가 붙은 시각은 읽기를 확정할 수 없습니다.",
            )
        left = self._render_time(left_token)
        right = self._render_time(right_token)
        if left.unresolved or right.unresolved:
            return ambiguous(token, "ambiguous_numeric", "유효하지 않은 시각 범위입니다.")
        return _Rendered(
            f"{left.text}에서 {right.text}",
            Handler.NUMERIC,
            "normalizer.clock_range.v1",
        )

    def _render_iso_currency(self, token: str) -> _Rendered:
        match = expected_match(_ISO_CURRENCY_RE, token)
        code = match.group("prefix") or match.group("suffix")
        number = match.group("prefix_number") or match.group("suffix_number")
        assert code is not None and number is not None
        spoken_unit = match.group("spoken_unit")
        if spoken_unit is not None and spoken_unit != _ISO_CURRENCIES[code]:
            return ambiguous(
                token,
                "ambiguous_numeric",
                "ISO 통화 코드와 발화 단위가 서로 다릅니다.",
            )
        return render_number(
            number,
            suffix=_ISO_CURRENCIES[code],
            rule_id="normalizer.currency_iso.v1",
            original=token,
        )

    def _render_scaled_currency(self, token: str) -> _Rendered:
        match = expected_match(_SCALED_CURRENCY_RE, token)
        try:
            if may_be_thousands_separator(parse_number(match.group("number"))):
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "점이 천 단위 구분점일 수 있어 원문을 보존합니다.",
                )
            scaled = scale_decimal(match.group("number"), _SCALE_POWERS[match.group("scale")])
        except NumberFormatError:
            return ambiguous(token, "ambiguous_numeric", "축약 금액을 손실 없이 읽을 수 없습니다.")
        rendered = render_number(
            scaled,
            suffix="원",
            rule_id="normalizer.currency_scaled.v1",
            original=token,
            allow_long=True,
        )
        suffix = match.group("suffix") or ""
        if rendered.unresolved or not suffix:
            return rendered
        return _Rendered(rendered.text + suffix, rendered.handler, rendered.rule_id)


    def _render_scaled_quantity(self, token: str) -> _Rendered:
        """큰 배율과 그 안의 작은 배율을 구분해 수량의 정확한 값을 합친다."""

        match = expected_match(_SCALED_QUANTITY_RE, token)
        word = match.group("word")
        unit = next((item for item in _ALL_UNITS if word.startswith(item)), "")
        suffix = word[len(unit):]
        if not unit or (suffix and suffix not in _KOREAN_SUFFIXES):
            return ambiguous(token, "ambiguous_numeric", "단위 뒤의 낱말을 확정할 수 없습니다.")
        components = list(_SCALED_COMPONENT_RE.finditer(match.group("body")))
        sign = ""
        previous_small: int | None = None
        previous_large: int | None = None
        try:
            # 입력의 모든 자릿수와 배율 및 덧셈의 올림을 담을 정밀도를 확보한다.
            # float 또는 Decimal의 기본 정밀도로 중간 값을 반올림하지 않는다.
            precision = len(token) + max(_SCALE_POWERS.values()) + 2
            with localcontext(Context(prec=precision)):
                total = Decimal(0)
                section = Decimal(0)
                for index, component in enumerate(components):
                    number = component.group("number")
                    parsed = parse_number(number)
                    if (len(parsed.integer) > 10 or has_ambiguous_leading_zero(parsed)
                            or may_be_thousands_separator(parsed)):
                        raise NumberFormatError("배율 계수의 용도를 확정할 수 없습니다.")
                    if index and parsed.sign:
                        raise NumberFormatError("배율 사슬 안의 부호를 수량으로 합치지 않습니다.")
                    if not index:
                        sign = parsed.sign
                    small = component.group("small")
                    power = _SCALE_POWERS[small] if small is not None else 0
                    if previous_small is not None and power >= previous_small:
                        raise NumberFormatError("소그룹의 작은 배율이 내림차순이 아닙니다.")
                    unsigned = number[1:] if parsed.sign else number
                    value = Decimal(scale_decimal(unsigned, power))
                    if previous_small is not None and value >= Decimal(10) ** previous_small:
                        raise NumberFormatError("하위 항이 앞 배율의 범위를 넘습니다.")
                    section += value
                    previous_small = power
                    large = component.group("large")
                    if large is not None:
                        large_power = _SCALE_POWERS[large]
                        if previous_large is not None and large_power >= previous_large:
                            raise NumberFormatError("큰 배율이 엄격한 내림차순이 아닙니다.")
                        contribution = section * (Decimal(10) ** large_power)
                        if previous_large is not None and contribution >= Decimal(10) ** previous_large:
                            raise NumberFormatError("큰 배율의 하위 소그룹이 범위를 넘습니다.")
                        total += contribution
                        section = Decimal(0)
                        previous_small = None
                        previous_large = large_power
                if previous_large is not None and section >= Decimal(10) ** previous_large:
                    raise NumberFormatError("마지막 소그룹이 앞 큰 배율을 넘습니다.")
                total += section
                magnitude = format(total, "f")
                if "." in magnitude:
                    magnitude = magnitude.rstrip("0").rstrip(".")
                surface = sign + magnitude
        except NumberFormatError:
            return ambiguous(token, "ambiguous_numeric", "배율 사슬을 손실 없이 확정할 수 없습니다.")
        rendered = render_number(surface, rule_id="normalizer.number.sino.v1", original=token, allow_long=True)
        if rendered.unresolved:
            return rendered
        spoken = read_native_or_sino(surface) if unit in _NATIVE_COUNTERS else rendered.text
        approximation = match.group("approximation")
        # 기존 단일 배율 물리 단위의 규칙 식별자를 그대로 유지한다.
        rule = "scaled_quantity" if len(components) > 1 else "scaled_unit"
        if approximation is not None:
            rule = "scaled_approximate_unit" if len(components) == 1 else "scaled_quantity"
        return _Rendered(
            format_quantity(spoken, unit, number_suffix="여" if approximation is not None else "") + suffix,
            Handler.NUMERIC,
            f"normalizer.{rule}.v1",
        )

    def _render_nights_days(self, token: str) -> _Rendered:
        """붙여 쓴 숙박 기간도 하나의 구조화 수량으로 검증한다."""

        match = expected_match(_NIGHTS_DAYS_RE, token)
        suffix = match.group("suffix")
        if suffix and suffix not in _KOREAN_SUFFIXES:
            return ambiguous(token, "ambiguous_numeric", "기간 뒤의 낱말을 확정할 수 없습니다.")
        spoken = []
        for name, unit in (("nights", "박"), ("days", "일")):
            number = match.group(name)
            try:
                parsed = parse_number(number)
                if parsed.sign or parsed.fraction is not None:
                    raise NumberFormatError("숙박 기간이 단순한 정수 표기가 아닙니다.")
            except NumberFormatError:
                return ambiguous(token, "ambiguous_numeric", "숙박 기간을 손실 없이 읽을 수 없습니다.")
            rendered = render_number(number, suffix=unit, rule_id="normalizer.number.sino.v1", original=token)
            if rendered.unresolved:
                return ambiguous(token, "ambiguous_numeric", "숙박 기간을 손실 없이 읽을 수 없습니다.")
            spoken.append(rendered.text)
        return _Rendered(" ".join(spoken) + suffix, Handler.NUMERIC, "normalizer.duration_nights_days.v1")

    def _render_number_hangul_unit(
        self,
        token: str,
        *,
        force_sino: bool,
        number_run: NumberReadingRun | None = None,
        start: int | None = None,
        context_end: int | None = None,
    ) -> _Rendered:
        match = expected_match(_NUMBER_HANGUL_UNIT_RE, token)
        word = match.group("word")
        unit = next((item for item in _ALL_UNITS if word.startswith(item)), "")
        suffix = word[len(unit) :]
        if not unit or (suffix and suffix not in _KOREAN_SUFFIXES):
            return ambiguous(
                token,
                "ambiguous_numeric",
                "단위인지 더 긴 낱말인지 확정할 수 없습니다.",
            )
        rendered = self._render_number_unit(
            match.group("number"),
            unit,
            original=token,
            force_sino=force_sino,
            number_run=number_run,
            number_start=None if start is None else start + match.start("number"),
            context_end=(
                context_end
                if context_end is not None
                else (None if start is None else start + len(token))
            ),
        )
        if rendered.unresolved:
            return rendered
        return _Rendered(rendered.text + suffix, rendered.handler, rendered.rule_id)

    @staticmethod
    def _consultable_number(number: str) -> bool:
        """판별기에 물어볼 수 있는 단순 정수 표기인지 본다.

        부호·쉼표·소수점이 있거나 선행 0이 있거나 아주 긴 숫자는 규칙이
        이미 보존이나 별도 경로로 다루므로 문맥 판별 대상이 아니다.
        """

        return (
            number.isascii()
            and number.isdigit()
            and 1 <= len(number) <= 10
            and not (len(number) > 1 and number.startswith("0"))
        )

    def _apply_bare_number_context(
        self,
        rendered: _Rendered,
        number: str,
        number_run: NumberReadingRun | None,
        start: int | None,
        context_end: int | None = None,
    ) -> _Rendered:
        """맨숫자의 문맥 결정은 낱자리 또는 독립형 고유어 수사로 읽는다.

        단위 없는 고유어는 하나·둘·셋·넷·스물처럼 독립형을 쓴다.
        기존 v1 판별기는 이 자리에서 낱자리 교정만 반환한다.
        """

        if number_run is None or start is None or not self._consultable_number(number):
            return rendered
        decision = number_run.decide(
            start,
            start + len(number),
            unit="",
            site="bare",
            default="sino",
            context_end=context_end,
        )
        if decision == "native":
            return _Rendered(
                read_native_standalone_or_sino(number),
                Handler.NUMERIC,
                "normalizer.number_context_native.v1",
            )
        if decision != "digitwise":
            return rendered
        return _Rendered(
            read_digitwise(number),
            Handler.NUMERIC,
            "normalizer.number_context_digitwise.v1",
        )


    def _render_quantity_unit(
        self,
        token: str,
        *,
        force_sino: bool,
        number_run: NumberReadingRun | None = None,
        start: int | None = None,
        context_end: int | None = None,
    ) -> _Rendered:
        """일반 수·분수·단일 배율 수와 단위를 한 토큰으로 읽는다."""

        match = expected_match(_QUANTITY_UNIT_RE, token)
        unit = match.group("unit")
        numerator = match.group("numerator")
        if numerator is not None:
            # 혈압의 `120/80mmHg`는 분수가 아니라 두 측정값의 비율 표기다.
            if unit == "mmHg":
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "수은주밀리미터 앞의 슬래시는 혈압 비율일 수 있어 원문을 보존합니다.",
                )
            fraction_surface = f"{numerator}/{match.group('denominator')}"
            rendered = render_fraction(fraction_surface)
            if rendered.unresolved:
                return ambiguous(
                    token,
                    rendered.diagnostic_code or "ambiguous_numeric",
                    rendered.diagnostic_message or "분수를 손실 없이 읽을 수 없습니다.",
                )
            return _Rendered(
                format_quantity(rendered.text, unit),
                Handler.NUMERIC,
                "normalizer.fraction_unit.v1",
            )

        number = match.group("number")
        if number is None:
            raise InternalInvariantError("수량 단위 토큰에 숫자가 없습니다.")
        scale = match.group("scale")
        approximation = match.group("approximation")
        if scale is None and approximation is None:
            return self._render_number_unit(
                number,
                unit,
                original=token,
                force_sino=force_sino,
                number_run=number_run,
                number_start=None if start is None else start + match.start("number"),
                context_end=context_end,
            )

        try:
            parsed = parse_number(number)
            if len(parsed.integer) > 10:
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "긴 숫자가 식별번호인지 수량인지 확정할 수 없습니다.",
                )
            if scale is not None and may_be_thousands_separator(parsed):
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "점이 천 단위 구분점일 수 있어 원문을 보존합니다.",
                )
            scaled = (
                scale_decimal(number, _SCALE_POWERS[scale])
                if scale is not None
                else number
            )
        except NumberFormatError:
            return ambiguous(token, "ambiguous_numeric", "수량을 손실 없이 읽을 수 없습니다.")
        rendered_number = render_number(
            scaled,
            rule_id="normalizer.number.sino.v1",
            original=token,
            allow_long=scale is not None,
        )
        if rendered_number.unresolved:
            return rendered_number
        rule = "scaled_unit" if scale is not None else "approximate_unit"
        if scale is not None and approximation is not None:
            rule = "scaled_approximate_unit"
        return _Rendered(
            format_quantity(
                rendered_number.text,
                unit,
                number_suffix="여" if approximation is not None else "",
            ),
            Handler.NUMERIC,
            f"normalizer.{rule}.v1",
        )


    def _render_number_unit(
        self,
        number: str,
        unit: str,
        *,
        original: str | None = None,
        force_sino: bool = False,
        number_run: NumberReadingRun | None = None,
        number_start: int | None = None,
        context_end: int | None = None,
        include_speed_prefix: bool = True,
    ) -> _Rendered:
        source = original if original is not None else number + unit
        try:
            parsed = parse_number(number)
            month_number = parsed.integer.lstrip("0") or "0"
            if (
                unit == "월"
                and not force_sino
                and not parsed.sign
                and parsed.fraction is None
                and month_number in {"6", "10"}
            ):
                return _Rendered(
                    "유월" if month_number == "6" else "시월",
                    Handler.NUMERIC,
                    "normalizer.month_exception.v1",
                )
            if has_ambiguous_leading_zero(parsed) and parsed.fraction is None:
                return ambiguous(
                    source,
                    "ambiguous_numeric",
                    "선행 0이 있는 숫자의 용도를 확정할 수 없습니다.",
                )
            if unit in _CURRENCY_UNIT_WORDS and may_be_thousands_separator(parsed):
                return ambiguous(
                    source,
                    "ambiguous_numeric",
                    "점이 천 단위 구분점일 수 있어 원문을 보존합니다.",
                )
            if len(parsed.integer) > 10:
                return ambiguous(
                    source,
                    "ambiguous_numeric",
                    "긴 숫자가 식별번호인지 수량인지 확정할 수 없습니다.",
                )
            if (
                unit == "번째"
                and not force_sino
                and not parsed.sign
                and parsed.integer == "1"
                and parsed.fraction is None
            ):
                spoken_number = "첫"
            elif force_sino or unit not in _NATIVE_COUNTERS:
                spoken_number = read_sino(number)
            else:
                spoken_number = read_native_or_sino(number)
        except NumberFormatError:
            return ambiguous(
                source,
                "ambiguous_numeric",
                "숫자 표면형을 손실 없이 읽을 수 없습니다.",
            )
        if force_sino:
            rule = "ordinal_sino"
        elif unit in _NATIVE_COUNTERS:
            rule = "native_counter"
        else:
            rule = "sino_unit"
        # `제N`처럼 표기가 읽기를 정하는 자리와 `1번째`→`첫`처럼 규칙이 이미
        # 특수형을 쓰는 자리는 문맥 판별 대상이 아니다.
        if (
            not force_sino
            and spoken_number != "첫"
            and unit not in _CONTEXT_INDEPENDENT_SINO_UNITS
            and unit not in _CONTEXT_INDEPENDENT_NATIVE_COUNTERS
        ):
            default = "native" if unit in _NATIVE_COUNTERS else "sino"
            contextual = self._decide_number_reading(
                number, unit, number_run, number_start, default, context_end
            )
            if contextual is not None:
                return _Rendered(
                    format_quantity(
                        contextual[0],
                        unit,
                        include_speed_prefix=include_speed_prefix,
                    ),
                    Handler.NUMERIC,
                    f"normalizer.number_context_{contextual[1]}.v1",
                )
        rule_id = (
            "normalizer.speed_unit.v1"
            if unit in _SPEED_UNIT_READINGS
            else f"normalizer.number_{rule}.v1"
        )
        return _Rendered(
            format_quantity(
                spoken_number,
                unit,
                include_speed_prefix=include_speed_prefix,
            ),
            Handler.NUMERIC,
            rule_id,
        )

    def _decide_number_reading(
        self,
        number: str,
        unit: str,
        number_run: NumberReadingRun | None,
        number_start: int | None,
        default: str,
        context_end: int | None = None,
    ) -> tuple[str, str] | None:
        """단위가 붙은 숫자를 문맥에 따라 다시 읽어야 하는지 판단한다."""

        if (
            number_run is None
            or number_start is None
            or not self._consultable_number(number)
        ):
            return None
        decision = number_run.decide(
            number_start,
            number_start + len(number),
            unit=unit,
            site="unit",
            default=default,
            context_end=context_end,
        )
        if decision is None:
            return None
        if decision == "native":
            return read_native_or_sino(number), "native"
        if decision == "digitwise":
            return read_digitwise(number), "digitwise"
        return read_sino(number), "sino"


    def _render_range(self, token: str, *, kind: str) -> _Rendered:
        if kind == "range_both":
            match = expected_match(_RANGE_BOTH_RE, token)
            left = self._render_range_side(match.group("left"), match.group("left_unit"))
            right = self._render_range_side(match.group("right"), match.group("unit"))
            if left.unresolved or right.unresolved:
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "범위의 숫자를 손실 없이 읽을 수 없습니다.",
                )
            return _Rendered(
                f"{left.text}에서 {right.text}{match.group('suffix') or ''}",
                Handler.NUMERIC,
                "normalizer.range_dual_unit.v1",
            )

        if kind == "scaled_range":
            match = expected_match(_SCALED_RANGE_RE, token)
            try:
                if may_be_thousands_separator(parse_number(match.group("left"))):
                    return ambiguous(
                        token,
                        "ambiguous_numeric",
                        "점이 천 단위 구분점일 수 있어 원문을 보존합니다.",
                    )
                left_scaled = scale_decimal(
                    match.group("left"), _SCALE_POWERS[match.group("left_scale")]
                )
                left_spoken = read_sino(left_scaled)
            except NumberFormatError:
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "축약 금액을 손실 없이 읽을 수 없습니다.",
                )
            right = self._render_scaled_currency(
                match.group("right") + match.group("right_scale") + "원"
            )
            if right.unresolved:
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "축약 금액을 손실 없이 읽을 수 없습니다.",
                )
            return _Rendered(
                f"{left_spoken}에서 {right.text}{match.group('suffix') or ''}",
                Handler.NUMERIC,
                "normalizer.range_scaled_currency.v1",
            )

        if kind != "range":
            raise InternalInvariantError(f"알 수 없는 범위 토큰입니다: {kind}")
        match = expected_match(_RANGE_RE, token)
        unit = match.group("unit")
        grammatical_suffix = match.group("suffix") or ""
        if unit == "시":
            return ambiguous(
                token,
                "ambiguous_numeric",
                "축약된 시간 범위인지 수량 범위인지 확정할 수 없습니다.",
            )
        if unit is None:
            left_number = render_number(
                match.group("left"),
                rule_id="normalizer.range_number.v1",
            )
            right_number = render_number(
                match.group("right"),
                rule_id="normalizer.range_number.v1",
            )
            if left_number.unresolved or right_number.unresolved:
                return ambiguous(
                    token,
                    "ambiguous_numeric",
                    "범위의 숫자를 손실 없이 읽을 수 없습니다.",
                )
            return _Rendered(
                f"{left_number.text}에서 {right_number.text}{grammatical_suffix}",
                Handler.NUMERIC,
                "normalizer.range_number.v1",
            )
        left = self._render_range_left_endpoint(match.group("left"), unit)
        speed = _SPEED_UNIT_READINGS.get(unit)
        right = self._render_range_side(
            match.group("right"),
            unit,
            include_speed_prefix=speed is None,
        )
        if left.unresolved or right.unresolved:
            return ambiguous(token, "ambiguous_numeric", "범위의 숫자를 손실 없이 읽을 수 없습니다.")
        prefix = f"{speed[0]} " if speed is not None else ""
        return _Rendered(
            f"{prefix}{left.text}에서 {right.text}{grammatical_suffix}",
            Handler.NUMERIC,
            "normalizer.range_speed.v1" if speed is not None else "normalizer.range_unit.v2",
        )

    def _render_range_left_endpoint(self, number: str, unit: str) -> _Rendered:
        """단위 없이 수사만 남는 범위 왼쪽 숫자를 단위의 수사계로 읽는다."""

        try:
            parsed = parse_number(number)
            if has_ambiguous_leading_zero(parsed) and parsed.fraction is None:
                return ambiguous(
                    number,
                    "ambiguous_numeric",
                    "선행 0이 있는 숫자의 용도를 확정할 수 없습니다.",
                )
            if unit in _NATIVE_COUNTERS:
                spoken = read_native_standalone_or_sino(number)
            else:
                spoken = read_sino(number)
        except NumberFormatError:
            return ambiguous(
                number,
                "ambiguous_numeric",
                "숫자 표면형을 손실 없이 읽을 수 없습니다.",
            )
        return _Rendered(spoken, Handler.NUMERIC, "normalizer.range_unit.v2")

    def _render_range_side(
        self,
        number: str,
        unit: str,
        *,
        include_speed_prefix: bool = True,
    ) -> _Rendered:
        """범위 한쪽 끝의 숫자와 단위를 단일 수량과 같은 규칙으로 읽는다."""

        if unit in {"%", "％", "%p", "%P"}:
            suffix = "퍼센트포인트" if unit.lower() == "%p" else "퍼센트"
            return render_number(
                number,
                suffix=suffix,
                rule_id="normalizer.range_percentage.v2",
            )
        if unit in {"만원", "억원", "조원"}:
            return self._render_scaled_currency(number + unit)
        return self._render_number_unit(
            number,
            unit,
            include_speed_prefix=include_speed_prefix,
        )


    @staticmethod
    def _read_letters(token: str) -> str:
        return spell_ascii_letters(token)
