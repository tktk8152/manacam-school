"""
ManaCam for KOKORYUSCHOOL - PDF出力モジュール
生成した類題を、先生がそのまま印刷して配れる形のPDFにする

問題プリント（生徒配布用）と解答プリント（先生用）の2枚を生成。
日本語フォントは reportlab 同梱の HeiseiKakuGo-W5（CIDフォント）を使う。
"""
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


JP_FONT = "HeiseiKakuGo-W5"
pdfmetrics.registerFont(UnicodeCIDFont(JP_FONT))


PRINT_STYLES = {
    "standard": {
        "margin": 20,            # mm
        "title_size": 16,
        "info_size": 10,
        "body_size": 11,
        "line_h": 6,             # mm
        "max_chars": 42,
        "ans_space_lines": 2,
    },
    "spacious": {
        "margin": 26,
        "title_size": 18,
        "info_size": 11,
        "body_size": 14,
        "line_h": 8,
        "max_chars": 30,
        "ans_space_lines": 3,
    },
    "compact": {
        "margin": 15,
        "title_size": 14,
        "info_size": 9,
        "body_size": 10,
        "line_h": 5,
        "max_chars": 50,
        "ans_space_lines": 1,
    },
}


def _get_style(name: str) -> dict:
    return PRINT_STYLES.get(name, PRINT_STYLES["standard"])


def _draw_header(c: canvas.Canvas, title: str, unit: str, grade: str,
                 difficulty: str = "", estimated_minutes: int = 0,
                 style: dict = None, include_score: bool = False, score_max: int = 100):
    """ヘッダ（塾名・タイトル・単元・学年・難易度・目安時間・名前・点数）を描画"""
    style = style or _get_style("standard")
    margin = style["margin"] * mm
    width, height = A4

    c.setFont(JP_FONT, 9)
    c.drawString(margin, height - 15 * mm, "ココリュウスクール")
    c.drawRightString(width - margin, height - 15 * mm,
                      datetime.now().strftime("%Y/%m/%d"))

    c.setFont(JP_FONT, style["title_size"])
    c.drawString(margin, height - 25 * mm, title)

    c.setFont(JP_FONT, style["info_size"])
    line2 = f"単元: {unit}    学年: {grade}"
    if difficulty:
        line2 += f"    難易度: {difficulty}"
    if estimated_minutes:
        line2 += f"    目安: {estimated_minutes}分"
    c.drawString(margin, height - 33 * mm, line2)

    # 右側の記入欄: 点数（任意）と 名前
    info_y = height - 33 * mm
    if include_score:
        # 点数 + 名前を2段で
        score_y = info_y
        name_y = info_y - 6 * mm
        # 点数: __ / N点
        score_label_x = width - margin - 50 * mm
        score_line_start = width - margin - 38 * mm
        score_line_end = width - margin - 18 * mm
        c.drawString(score_label_x, score_y, "点数:")
        c.setStrokeColorRGB(0.5, 0.5, 0.5)
        c.setLineWidth(0.4)
        c.line(score_line_start, score_y - 1 * mm, score_line_end, score_y - 1 * mm)
        c.drawString(width - margin - 16 * mm, score_y, f"/ {score_max}点")
        # 名前
        c.drawString(score_label_x, name_y, "名前:")
        c.line(score_line_start, name_y - 1 * mm, width - margin, name_y - 1 * mm)
        divider_y = info_y - 13 * mm
    else:
        # 名前のみ
        name_label_x = width - margin - 50 * mm
        name_line_start = width - margin - 40 * mm
        name_line_end = width - margin
        c.drawString(name_label_x, info_y, "名前:")
        c.setStrokeColorRGB(0.5, 0.5, 0.5)
        c.setLineWidth(0.4)
        c.line(name_line_start, info_y - 1 * mm, name_line_end, info_y - 1 * mm)
        divider_y = info_y - 7 * mm

    # ヘッダと問題エリアの区切り線
    c.setStrokeColorRGB(0.4, 0.4, 0.4)
    c.setLineWidth(0.5)
    c.line(margin, divider_y, width - margin, divider_y)

    return divider_y


def _wrap(text: str, max_chars: int) -> list[str]:
    """全角想定の素朴な折り返し。日本語は1文字=1単位として扱う。"""
    lines = []
    for paragraph in text.splitlines() or [text]:
        if not paragraph:
            lines.append("")
            continue
        for i in range(0, len(paragraph), max_chars):
            lines.append(paragraph[i:i + max_chars])
    return lines


_SUPERSCRIPT_TRANSLATION = str.maketrans({
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
})
_INLINE_FRACTION_RE = re.compile(r"(?<![\d./])(\d+)\s*/\s*(\d+)(?![\d./])")
_INLINE_SUPERSCRIPT_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\^(\d+)|([⁰¹²³⁴⁵⁶⁷⁸⁹]+)|の?(\d+)乗)")


def _normalize_inline_math_text(text: str) -> str:
    return str(text or "").translate(_FORMULA_TRANSLATION).translate(str.maketrans({
        "／": "/",
        "＾": "^",
    }))


def _needs_inline_math(text: str) -> bool:
    normalized = _normalize_inline_math_text(text)
    return bool(_INLINE_FRACTION_RE.search(normalized) or
                _INLINE_SUPERSCRIPT_RE.search(normalized))


def _inline_math_tokens(text: str) -> list[dict]:
    normalized = _normalize_inline_math_text(text)
    tokens = []
    pos = 0
    while pos < len(normalized):
        fraction_match = _INLINE_FRACTION_RE.search(normalized, pos)
        sup_match = _INLINE_SUPERSCRIPT_RE.search(normalized, pos)
        matches = [m for m in (fraction_match, sup_match) if m]
        if not matches:
            tokens.append({"type": "text", "text": normalized[pos:]})
            break

        match = min(matches, key=lambda m: m.start())
        if match.start() > pos:
            tokens.append({"type": "text", "text": normalized[pos:match.start()]})

        if match.re is _INLINE_FRACTION_RE:
            tokens.append({
                "type": "fraction",
                "num": match.group(1),
                "den": match.group(2),
            })
        else:
            exponent = (
                match.group(2) or
                (match.group(3) or "").translate(_SUPERSCRIPT_TRANSLATION) or
                match.group(4)
            )
            tokens.append({
                "type": "sup",
                "base": match.group(1),
                "exp": exponent,
            })
        pos = match.end()
    return [token for token in tokens if token.get("text") or token.get("num") or token.get("base")]


def _measure_inline_math(tokens: list[dict], font_size: float) -> float:
    width = 0
    for token in tokens:
        if token["type"] == "text":
            width += pdfmetrics.stringWidth(token["text"], JP_FONT, font_size)
        elif token["type"] == "fraction":
            frac_size = font_size * 0.68
            num_w = pdfmetrics.stringWidth(token["num"], "Helvetica", frac_size)
            den_w = pdfmetrics.stringWidth(token["den"], "Helvetica", frac_size)
            width += max(num_w, den_w) + 2
        elif token["type"] == "sup":
            sup_size = font_size * 0.58
            width += pdfmetrics.stringWidth(token["base"], "Helvetica", font_size)
            width += pdfmetrics.stringWidth(token["exp"], "Helvetica", sup_size)
    return width


def _draw_inline_math_line(c: canvas.Canvas, text: str, x: float, y: float,
                           max_width: float, font_size: float,
                           stroke_color: tuple[float, float, float] = (0, 0, 0)):
    """分数や指数を小さく組み、1行に収まるよう縮小して描画する。"""
    tokens = _inline_math_tokens(text)
    if not tokens:
        return

    measured = _measure_inline_math(tokens, font_size)
    scale = 1.0
    if measured > max_width and measured > 0:
        scale = max(0.55, max_width / measured)
    size = font_size * scale
    cursor = x

    c.saveState()
    c.setStrokeColorRGB(*stroke_color)
    for token in tokens:
        if token["type"] == "text":
            c.setFont(JP_FONT, size)
            c.drawString(cursor, y, token["text"])
            cursor += pdfmetrics.stringWidth(token["text"], JP_FONT, size)
            continue

        if token["type"] == "fraction":
            frac_size = size * 0.68
            num_w = pdfmetrics.stringWidth(token["num"], "Helvetica", frac_size)
            den_w = pdfmetrics.stringWidth(token["den"], "Helvetica", frac_size)
            frac_w = max(num_w, den_w) + 2 * scale
            center_x = cursor + frac_w / 2
            bar_y = y + size * 0.08

            c.setFont("Helvetica", frac_size)
            c.drawString(center_x - num_w / 2, bar_y + frac_size * 0.25, token["num"])
            c.drawString(center_x - den_w / 2, bar_y - frac_size * 1.02, token["den"])
            c.setLineWidth(max(0.45, 0.7 * scale))
            c.line(cursor, bar_y, cursor + frac_w, bar_y)
            cursor += frac_w + 1.5 * scale
            continue

        if token["type"] == "sup":
            sup_size = size * 0.58
            c.setFont("Helvetica", size)
            c.drawString(cursor, y, token["base"])
            cursor += pdfmetrics.stringWidth(token["base"], "Helvetica", size)
            c.setFont("Helvetica", sup_size)
            c.drawString(cursor, y + size * 0.45, token["exp"])
            cursor += pdfmetrics.stringWidth(token["exp"], "Helvetica", sup_size)
    c.restoreState()


def _draw_text_or_inline_math(c: canvas.Canvas, text: str, x: float, y: float,
                              max_width: float, max_chars: int, line_h: float,
                              font_size: float,
                              stroke_color: tuple[float, float, float] = (0, 0, 0)) -> float:
    if _needs_inline_math(text):
        _draw_inline_math_line(c, text, x, y, max_width, font_size, stroke_color)
        return y - line_h

    c.setFont(JP_FONT, font_size)
    for line in _wrap(text, max_chars=max_chars):
        c.drawString(x, y, line)
        y -= line_h
    return y


def _draw_work_grid(c: canvas.Canvas, x: float, y: float, width: float,
                    rows: int = 6, cell_mm: int = 5) -> float:
    """筆算・計算メモ用の方眼を描画し、描画後のy座標を返す。"""
    cell = cell_mm * mm
    height = rows * cell
    cols = int(width // cell)
    grid_w = cols * cell

    c.setStrokeColorRGB(0.78, 0.78, 0.78)
    c.setLineWidth(0.25)
    for col in range(cols + 1):
        px = x + col * cell
        c.line(px, y, px, y - height)
    for row in range(rows + 1):
        py = y - row * cell
        c.line(x, py, x + grid_w, py)
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    return y - height


_FORMULA_TRANSLATION = str.maketrans({
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "＋": "+", "－": "-", "−": "-", "＊": "*", "．": ".",
    "＝": "=", "　": " ",
})

_NUMBER_PATTERN = r"\d{1,7}(?:\.\d{1,7})?"
_ARITHMETIC_EXPR_RE = re.compile(
    rf"(?<![\d./])({_NUMBER_PATTERN}(?:\s*[+\-*xX×÷]\s*{_NUMBER_PATTERN})+)\s*="
)
_ARITHMETIC_EXPR_FULL_RE = re.compile(
    rf"{_NUMBER_PATTERN}(?:\s*[+\-*xX×÷]\s*{_NUMBER_PATTERN})+\s*=\s*"
)
_ARITHMETIC_TOKEN_RE = re.compile(rf"{_NUMBER_PATTERN}|[+\-*xX×÷]")


def _parse_vertical_arithmetic(text: str) -> dict | None:
    """整数どうしの式を、筆算配置用に取り出す。"""
    normalized = str(text or "").translate(_FORMULA_TRANSLATION)
    match = _ARITHMETIC_EXPR_RE.search(normalized)
    if not match:
        return None

    tokens = _ARITHMETIC_TOKEN_RE.findall(match.group(1))
    if len(tokens) < 3 or len(tokens) % 2 == 0:
        return None

    terms = tokens[0::2]
    ops = [
        {
            "+": "+",
            "-": "-",
            "*": "×",
            "x": "×",
            "X": "×",
            "×": "×",
            "÷": "÷",
        }[op]
        for op in tokens[1::2]
    ]
    if "÷" in ops and (len(ops) != 1 or ops[0] != "÷"):
        return None
    if "×" in ops and len(ops) != 1:
        return None
    return {"terms": terms, "ops": ops, "raw": match.group(0).strip()}


def _is_plain_vertical_arithmetic(text: str) -> bool:
    """式だけの問題なら、通常の横書き問題文を省いて筆算レイアウトにする。"""
    normalized = str(text or "").translate(_FORMULA_TRANSLATION).strip()
    return _ARITHMETIC_EXPR_FULL_RE.fullmatch(normalized) is not None


def _calculate_result_text(expr: dict) -> str | None:
    """幅の見積もり用に答えを計算する。PDFには答えを出さない。"""
    try:
        terms = [Decimal(term) for term in expr["terms"]]
    except InvalidOperation:
        return None
    ops = expr["ops"]

    value = terms[0]
    for op, term in zip(ops, terms[1:]):
        if op == "+":
            value += term
        elif op == "-":
            value -= term
        elif op == "×":
            value *= term
        elif op == "÷" and term:
            value //= term
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _split_number_text(value: str) -> tuple[str, str, bool]:
    value = str(value).strip().lstrip("-")
    if "." in value:
        left, right = value.split(".", 1)
        return left or "0", right, True
    return value, "", False


def _number_layout_for_expr(expr: dict) -> dict:
    values = list(expr["terms"])
    result = _calculate_result_text(expr)
    if result and expr["ops"] != ["÷"]:
        values.append(result)

    parts = [_split_number_text(value) for value in values]
    int_width = max(len(left) for left, _, _ in parts)
    frac_width = max(len(right) for _, right, _ in parts)
    has_decimal = any(has_dot for _, _, has_dot in parts)
    include_decimal = has_decimal or frac_width > 0
    cols = int_width + frac_width + (1 if include_decimal else 0)
    return {
        "cols": max(2, cols),
        "int_width": int_width,
        "frac_width": frac_width,
        "include_decimal": include_decimal,
    }


def _format_number_for_layout(value: str, layout: dict) -> str:
    left, right, has_dot = _split_number_text(value)
    int_text = left.rjust(layout["int_width"])
    if not layout["include_decimal"]:
        return int_text.rjust(layout["cols"])
    dot = "." if has_dot else " "
    return (int_text + dot + right.ljust(layout["frac_width"])).rjust(layout["cols"])


def _cell_count_for_expr(expr: dict) -> int:
    return _number_layout_for_expr(expr)["cols"]


def _row_count_for_expr(expr: dict) -> int:
    terms = expr["terms"]
    ops = expr["ops"]
    if ops == ["×"]:
        return max(5, len(terms) + 3)
    if ops == ["÷"]:
        return 5
    return len(terms) + 2


def _draw_centered(c: canvas.Canvas, text: str, x: float, y: float,
                   font: str, size: float):
    c.setFont(font, size)
    c.drawCentredString(x, y - size * 0.35, text)


def _draw_number_row(c: canvas.Canvas, value: str, row: int, grid_x: float,
                     top_y: float, layout: dict, cell: float, digit_size: float):
    text = _format_number_for_layout(value, layout)
    center_y = top_y - (row + 0.5) * cell
    for col, char in enumerate(text):
        if char == " ":
            continue
        center_x = grid_x + (col + 0.5) * cell
        size = digit_size * 0.82 if char == "." else digit_size
        _draw_centered(c, char, center_x, center_y, "Helvetica", size)


def _draw_vertical_stack_problem(c: canvas.Canvas, index: int | None, expr: dict,
                                 block_x: float, top_y: float, block_w: float,
                                 cell: float) -> float:
    """たし算・ひき算・かけ算の筆算マスを描画し、高さを返す。"""
    terms = expr["terms"]
    ops = expr["ops"]
    rows = _row_count_for_expr(expr)
    layout = _number_layout_for_expr(expr)
    cols = layout["cols"]
    grid_w = cols * cell
    grid_h = rows * cell
    left_pad = 17 * mm if index is not None else 9 * mm
    grid_x = block_x + left_pad
    if grid_x + grid_w > block_x + block_w - 2 * mm:
        grid_x = block_x + block_w - grid_w - 2 * mm

    pale_teal = (0.48, 0.72, 0.74)
    digit_size = min(18, cell * 0.84)

    c.saveState()
    if index is not None:
        c.setFillColorRGB(0, 0, 0)
        c.setFont(JP_FONT, 10)
        c.drawString(block_x, top_y - 0.75 * cell, f"({index})")

    # マス目
    c.setStrokeColorRGB(*pale_teal)
    c.setLineWidth(0.35)
    c.rect(grid_x, top_y - grid_h, grid_w, grid_h, stroke=1, fill=0)
    c.setDash(1.2, 2)
    for col in range(1, cols):
        x = grid_x + col * cell
        c.line(x, top_y, x, top_y - grid_h)
    for row in range(1, rows):
        if row == len(terms):
            continue
        y = top_y - row * cell
        c.line(grid_x, y, grid_x + grid_w, y)
    c.setDash()

    # 答えを書く線
    answer_line_y = top_y - len(terms) * cell
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1.0)
    c.line(grid_x - 9 * mm, answer_line_y, grid_x + grid_w, answer_line_y)

    # 数字と演算記号
    c.setFillColorRGB(0, 0, 0)
    for term_index, term in enumerate(terms):
        row = term_index
        _draw_number_row(c, term, row, grid_x, top_y, layout, cell, digit_size)
        if term_index > 0:
            _draw_centered(
                c,
                ops[term_index - 1],
                grid_x - 6 * mm,
                top_y - (row + 0.5) * cell,
                JP_FONT,
                min(18, cell * 0.9),
            )
    c.restoreState()
    return grid_h


def _draw_vertical_division_problem(c: canvas.Canvas, index: int | None, expr: dict,
                                    block_x: float, top_y: float, block_w: float,
                                    cell: float) -> float:
    """わり算の筆算マスを描画し、高さを返す。"""
    dividend, divisor = expr["terms"]
    rows = _row_count_for_expr(expr)
    layout = _number_layout_for_expr(expr)
    cols = layout["cols"]
    grid_w = cols * cell
    grid_h = rows * cell
    left_pad = 20 * mm if index is not None else 13 * mm
    grid_x = block_x + left_pad
    if grid_x + grid_w > block_x + block_w - 2 * mm:
        grid_x = block_x + block_w - grid_w - 2 * mm

    pale_teal = (0.48, 0.72, 0.74)
    digit_size = min(18, cell * 0.84)
    bracket_y = top_y - cell

    c.saveState()
    if index is not None:
        c.setFillColorRGB(0, 0, 0)
        c.setFont(JP_FONT, 10)
        c.drawString(block_x, top_y - 1.75 * cell, f"({index})")

    c.setStrokeColorRGB(*pale_teal)
    c.setLineWidth(0.35)
    c.rect(grid_x, top_y - grid_h, grid_w, grid_h, stroke=1, fill=0)
    c.setDash(1.2, 2)
    for col in range(1, cols):
        x = grid_x + col * cell
        c.line(x, top_y, x, top_y - grid_h)
    for row in range(1, rows):
        y = top_y - row * cell
        c.line(grid_x, y, grid_x + grid_w, y)
    c.setDash()

    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1.0)
    c.line(grid_x, bracket_y, grid_x + grid_w, bracket_y)
    c.line(grid_x, bracket_y, grid_x, top_y - 3 * cell)

    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", digit_size)
    c.drawRightString(grid_x - 2 * mm, top_y - 1.5 * cell - digit_size * 0.35,
                      divisor)
    _draw_number_row(c, dividend, 1, grid_x, top_y, layout, cell, digit_size)
    c.restoreState()
    return grid_h


def _draw_vertical_arithmetic_problem(c: canvas.Canvas, index: int | None,
                                      expr: dict, block_x: float, top_y: float,
                                      block_w: float, cell: float) -> float:
    if expr["ops"] == ["÷"]:
        return _draw_vertical_division_problem(c, index, expr, block_x, top_y,
                                               block_w, cell)
    return _draw_vertical_stack_problem(c, index, expr, block_x, top_y,
                                        block_w, cell)


def _render_vertical_arithmetic_sheet(c: canvas.Canvas, questions: list,
                                      style: dict, start_y: float) -> bool:
    """式だけの計算は、紙面を広く使う筆算レイアウトで描画する。"""
    parsed = []
    for qa in questions:
        q = qa.get("q", "")
        expr = _parse_vertical_arithmetic(q)
        if not expr or not _is_plain_vertical_arithmetic(q):
            return False
        parsed.append(expr)
    if not parsed:
        return False

    width, height = A4
    margin = style["margin"] * mm
    usable_w = width - margin * 2
    max_cells = max(_cell_count_for_expr(expr) for expr in parsed)
    max_rows = max(_row_count_for_expr(expr) for expr in parsed)
    cell = 7 * mm if max_cells <= 4 else 6 * mm
    min_block_w = max(39 * mm, max_cells * cell + 19 * mm)
    columns = min(4, max(1, int(usable_w // min_block_w)))
    block_w = usable_w / columns
    row_h = max_rows * cell + 8 * mm
    bottom_y = margin + 8 * mm
    row_top_y = start_y - 8 * mm

    for zero_index, expr in enumerate(parsed):
        col = zero_index % columns
        if col == 0 and row_top_y - max_rows * cell < bottom_y:
            c.showPage()
            row_top_y = height - margin - 8 * mm

        block_x = margin + col * block_w
        _draw_vertical_arithmetic_problem(
            c,
            zero_index + 1,
            expr,
            block_x,
            row_top_y,
            block_w,
            cell,
        )

        if col == columns - 1:
            row_top_y -= row_h

    return True


def _render_questions(c: canvas.Canvas, questions: list, with_answers: bool,
                      style: dict, start_y: float, include_work_grid: bool = False):
    """問題を描画。with_answers=True なら答えとヒントも出す。"""
    if not with_answers and include_work_grid:
        if _render_vertical_arithmetic_sheet(c, questions, style, start_y):
            return

    width, height = A4
    margin = style["margin"] * mm
    line_h = style["line_h"] * mm
    max_chars = style["max_chars"]
    body_size = style["body_size"]
    ans_space = style["ans_space_lines"]

    y = start_y - 6 * mm
    c.setFont(JP_FONT, body_size)

    for i, qa in enumerate(questions, 1):
        question_text = qa.get("q", "")
        expr = _parse_vertical_arithmetic(question_text) if not with_answers else None
        plain_expr = bool(expr and _is_plain_vertical_arithmetic(question_text))
        use_vertical_grid = bool(include_work_grid and expr and plain_expr)
        if with_answers:
            required_space = line_h * 5
        elif use_vertical_grid:
            inline_cell = 7 * mm if _cell_count_for_expr(expr) <= 4 else 6 * mm
            required_space = _row_count_for_expr(expr) * inline_cell + line_h + 5 * mm
        else:
            required_space = line_h * (2 + ans_space)

        if y - required_space < (margin + 8 * mm):
            c.showPage()
            c.setFont(JP_FONT, body_size)
            y = height - margin - 5 * mm

        if use_vertical_grid:
            inline_cell = 7 * mm if _cell_count_for_expr(expr) <= 4 else 6 * mm
            block_w = max(48 * mm, _cell_count_for_expr(expr) * inline_cell + 24 * mm)
            y -= _draw_vertical_arithmetic_problem(
                c,
                i,
                expr,
                margin,
                y,
                block_w,
                inline_cell,
            )
        else:
            head = f"({i}) {question_text}"
            y = _draw_text_or_inline_math(
                c,
                head,
                margin,
                y,
                width - margin * 2,
                max_chars,
                line_h,
                body_size,
            )

        if with_answers:
            ans = f"    答え: {qa.get('a', '')}"
            hint = qa.get("hint", "")
            steps = qa.get("steps", "")
            explanation = qa.get("explanation", "")
            c.setFillColorRGB(0.82, 0.10, 0.10)  # 赤
            y = _draw_text_or_inline_math(
                c,
                ans,
                margin,
                y,
                width - margin * 2,
                max_chars,
                line_h,
                body_size,
                stroke_color=(0.82, 0.10, 0.10),
            )
            c.setFillColorRGB(0, 0, 0)
            if steps:
                y = _draw_text_or_inline_math(
                    c,
                    f"    途中式: {steps}",
                    margin,
                    y,
                    width - margin * 2,
                    max_chars,
                    line_h,
                    body_size,
                )
            if explanation:
                y = _draw_text_or_inline_math(
                    c,
                    f"    解説: {explanation}",
                    margin,
                    y,
                    width - margin * 2,
                    max_chars,
                    line_h,
                    body_size,
                )
            if hint:
                y = _draw_text_or_inline_math(
                    c,
                    f"    ヒント: {hint}",
                    margin,
                    y,
                    width - margin * 2,
                    max_chars,
                    line_h,
                    body_size,
                )
        else:
            if use_vertical_grid:
                pass
            else:
                y -= line_h * ans_space  # 解答スペース

        y -= 7 * mm if use_vertical_grid else 2 * mm  # 設問間


def make_pdf(result: dict, out_path: Path, grade: str = "小5",
             difficulty: str = "", with_answer_page: bool = True,
             print_style: str = "standard",
             include_score: bool = False, score_max: int = 100,
             include_work_grid: bool = False) -> Path:
    """
    生成結果からプリントPDFを出力。

    Args:
        with_answer_page: True なら2ページ目に先生用解答を付ける
        print_style: "standard" / "spacious" / "compact"
        include_score: True なら点数欄を追加
        score_max: 満点（デフォ100点）
        include_work_grid: True なら数字だけの式を筆算マスにする

    Returns:
        書き出したファイルパス
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    style = _get_style(print_style)
    unit = result.get("unit", "（未判定）")
    questions = result.get("questions", [])
    estimated_minutes = result.get("estimated_minutes", 0)
    try:
        estimated_minutes = int(estimated_minutes) if estimated_minutes else 0
    except (TypeError, ValueError):
        estimated_minutes = 0

    c = canvas.Canvas(str(out_path), pagesize=A4)

    # 1ページ目: 生徒配布用
    divider_y = _draw_header(c, "算数 演習プリント", unit, grade,
                              difficulty, estimated_minutes,
                              style=style, include_score=include_score,
                              score_max=score_max)
    _render_questions(
        c,
        questions,
        with_answers=False,
        style=style,
        start_y=divider_y,
        include_work_grid=include_work_grid,
    )
    c.showPage()

    # 2ページ目: 先生用解答（オプション）
    if with_answer_page:
        divider_y = _draw_header(c, "解答・ヒント（先生用）", unit, grade,
                                  difficulty, estimated_minutes,
                                  style=style, include_score=False)
        _render_questions(c, questions, with_answers=True, style=style, start_y=divider_y)
        c.showPage()

    c.save()
    return out_path


if __name__ == "__main__":
    sample = {
        "unit": "2けたのたし算",
        "summary": "位をそろえて筆算する",
        "estimated_minutes": 10,
        "questions": [
            {"q": "13 + 11 =", "a": "24", "hint": "一の位から計算する"},
            {"q": "53 + 26 =", "a": "79", "hint": "位をそろえる"},
            {"q": "82 + 15 =", "a": "97", "hint": "十の位と一の位を見る"},
            {"q": "21 + 56 =", "a": "77", "hint": "一の位から計算する"},
            {"q": "46 + 15 =", "a": "61", "hint": "くり上がりに気をつける"},
            {"q": "62 + 19 =", "a": "81", "hint": "くり上がりに気をつける"},
            {"q": "26 + 46 =", "a": "72", "hint": "位をそろえる"},
            {"q": "19 + 53 =", "a": "72", "hint": "くり上がりに気をつける"},
        ],
    }
    for style in ["standard", "spacious", "compact"]:
        out = make_pdf(sample, Path(f"output_sample_{style}.pdf"), grade="小5",
                       print_style=style, include_score=True)
        print(f"✅ {style}: {out.resolve()}")
    grid_out = make_pdf(sample, Path("output_sample_work_grid.pdf"), grade="小5",
                        include_work_grid=True)
    print(f"✅ work_grid: {grid_out.resolve()}")
