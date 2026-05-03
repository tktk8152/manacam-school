"""
ManaCam for KOKORYUSCHOOL - PDF出力モジュール
生成した類題を、先生がそのまま印刷して配れる形のPDFにする

問題プリント（生徒配布用）と解答プリント（先生用）の2枚を生成。
日本語フォントは reportlab 同梱の HeiseiKakuGo-W5（CIDフォント）を使う。
"""
from pathlib import Path
from datetime import datetime

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


def _render_questions(c: canvas.Canvas, questions: list, with_answers: bool,
                      style: dict, start_y: float):
    """問題を描画。with_answers=True なら答えとヒントも出す。"""
    width, height = A4
    margin = style["margin"] * mm
    line_h = style["line_h"] * mm
    max_chars = style["max_chars"]
    body_size = style["body_size"]
    ans_space = style["ans_space_lines"]

    y = start_y - 6 * mm
    c.setFont(JP_FONT, body_size)

    for i, qa in enumerate(questions, 1):
        if y < (margin + 10 * mm):
            c.showPage()
            c.setFont(JP_FONT, body_size)
            y = height - margin - 5 * mm

        head = f"({i}) {qa.get('q', '')}"
        for line in _wrap(head, max_chars=max_chars):
            c.drawString(margin, y, line)
            y -= line_h

        if with_answers:
            ans = f"    答え: {qa.get('a', '')}"
            hint = qa.get("hint", "")
            steps = qa.get("steps", "")
            explanation = qa.get("explanation", "")
            c.setFillColorRGB(0.82, 0.10, 0.10)  # 赤
            for line in _wrap(ans, max_chars=max_chars):
                c.drawString(margin, y, line)
                y -= line_h
            c.setFillColorRGB(0, 0, 0)
            if steps:
                for line in _wrap(f"    途中式: {steps}", max_chars=max_chars):
                    c.drawString(margin, y, line)
                    y -= line_h
            if explanation:
                for line in _wrap(f"    解説: {explanation}", max_chars=max_chars):
                    c.drawString(margin, y, line)
                    y -= line_h
            if hint:
                for line in _wrap(f"    ヒント: {hint}", max_chars=max_chars):
                    c.drawString(margin, y, line)
                    y -= line_h
        else:
            y -= line_h * ans_space  # 解答スペース

        y -= 2 * mm  # 設問間


def make_pdf(result: dict, out_path: Path, grade: str = "小5",
             difficulty: str = "", with_answer_page: bool = True,
             print_style: str = "standard",
             include_score: bool = False, score_max: int = 100) -> Path:
    """
    生成結果からプリントPDFを出力。

    Args:
        with_answer_page: True なら2ページ目に先生用解答を付ける
        print_style: "standard" / "spacious" / "compact"
        include_score: True なら点数欄を追加
        score_max: 満点（デフォ100点）

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
    _render_questions(c, questions, with_answers=False, style=style, start_y=divider_y)
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
        "unit": "分数のたし算",
        "summary": "分母をそろえてからたす",
        "estimated_minutes": 10,
        "questions": [
            {"q": "1/2 + 1/3 =", "a": "5/6", "hint": "分母をそろえる"},
            {"q": "2/5 + 1/5 =", "a": "3/5", "hint": "分母が同じ"},
            {"q": "1/4 + 3/8 =", "a": "5/8", "hint": "1/4は2/8"},
        ],
    }
    for style in ["standard", "spacious", "compact"]:
        out = make_pdf(sample, Path(f"output_sample_{style}.pdf"), grade="小5",
                       print_style=style, include_score=True)
        print(f"✅ {style}: {out.resolve()}")
