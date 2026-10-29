"""미해석 토큰의 보존, 진단, 오류 정책을 적용한다."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from ..errors import ConversionPolicyError
from ..model import Diagnostic, Handler, Rewrite, RewriteStage, Severity, SourceSpan


@dataclass(frozen=True, slots=True)
class _Rendered:
    """한 토큰의 출력과 출처 및 미해석 정보를 보관한다."""

    text: str
    handler: Handler
    rule_id: str
    unresolved: bool = False
    diagnostic_code: str | None = None
    diagnostic_message: str | None = None


def ambiguous(token: str, code: str, message: str) -> _Rendered:
    return _Rendered(token, Handler.PROTECTED, f"normalizer.{code}.v1", True, code, message)


def raise_ambiguous(rendered: _Rendered, span: SourceSpan) -> None:
    raise ConversionPolicyError(
        rendered.diagnostic_code or "ambiguous_text",
        rendered.diagnostic_message or "안전하게 읽을 수 없어 원문을 보존했습니다.",
        source_span=span,
        rule_id=rendered.rule_id,
    )


def record_rendered(
    rendered: _Rendered,
    before: str,
    span: SourceSpan,
    rewrites: list[Rewrite],
    diagnostics: list[Diagnostic],
    *,
    on_ambiguous: str,
) -> None:
    if rendered.unresolved:
        if on_ambiguous == "error":
            raise_ambiguous(rendered, span)
        if on_ambiguous == "warn":
            diagnostics.append(
                Diagnostic(
                    rendered.diagnostic_code or "ambiguous_text",
                    rendered.diagnostic_message or "안전하게 읽을 수 없어 원문을 보존했습니다.",
                    Severity.WARNING,
                    (span,),
                    rendered.rule_id,
                    RewriteStage.VERBALIZATION,
                )
            )
    if rendered.text != before:
        rewrites.append(
            Rewrite(
                (span,), before, rendered.text, rendered.handler,
                rendered.rule_id, RewriteStage.VERBALIZATION,
            )
        )


def is_unsafe_attached_character(character: str) -> bool:
    code_point = ord(character)
    return (
        unicodedata.category(character).startswith("M")
        or unicodedata.category(character) == "Cf"
        or 0x1100 <= code_point <= 0x11FF
        or 0xA960 <= code_point <= 0xA97F
        or 0xD7B0 <= code_point <= 0xD7FF
    )


def is_permitted_whitespace(character: str) -> bool:
    """탭·줄바꿈과 Unicode 공백을 허용하되 나머지 제어 문자는 제외한다."""

    return character in "\t\r\n" or (
        character.isspace() and not unicodedata.category(character).startswith("C")
    )


def unsupported_character(character: str) -> tuple[str, str] | None:
    """허용한 한글·공백·문장부호 밖의 미해석 문자를 분류한다."""

    code_point = ord(character)
    category = unicodedata.category(character)
    if is_permitted_whitespace(character):
        return None
    if category in {"Cc", "Cf", "Co", "Cn", "Cs"}:
        return "unsupported_character", "제어·형식·비공개 문자는 TTS 입력으로 확정할 수 없습니다."
    if character.isnumeric() and not ("0" <= character <= "9"):
        return "ambiguous_numeric", "ASCII가 아닌 숫자의 읽기를 확정할 수 없습니다."
    if "가" <= character <= "힣":
        return None
    if 0x3131 <= code_point <= 0x318E or 0x1100 <= code_point <= 0x11FF:
        return "unsupported_script", "지원하지 않는 한글 자모 표기를 원문으로 보존합니다."
    if category.startswith("L") or category.startswith("M"):
        return "unsupported_script", "지원하지 않는 문자 체계는 원문으로 보존합니다."
    if category.startswith("S") or character in "=*<>^~∼":
        return "unsupported_symbol", "발화 규칙이 없는 의미 기호는 원문을 보존합니다."
    return None
