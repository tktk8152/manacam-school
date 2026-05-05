"""
ManaCam for KOKORYUSCHOOL - 小学算数の演習問題生成
市販テキストの問題ページから、似た形式の演習問題を生成する

LLM: Gemini 2.0 Flash（Google AI Studio無料枠 / クレカ不要）
SDK: google-genai（新公式SDK）
"""
import os
import sys
import json
import time
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
if not API_KEY or API_KEY == "ここに貼り付け":
    print("❌ GEMINI_API_KEY が設定されていません")
    print("   .env ファイルに以下を追加してください:")
    print("   GEMINI_API_KEY=AIzaSy...（Google AI Studioで取得）")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
FALLBACK_MODELS = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash,gemini-2.0-flash")
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


MAX_RETRIES = max(0, _env_int("GEMINI_MAX_RETRIES", 1))
RETRY_WAIT_SECONDS = max(0.0, _env_float("GEMINI_RETRY_WAIT_SECONDS", 2))


def _model_candidates() -> list[str]:
    """優先モデル + 混雑時の予備モデルを重複なしで返す。"""
    models = [MODEL_NAME]
    models.extend(m.strip() for m in FALLBACK_MODELS.split(",") if m.strip())
    unique = []
    for model in models:
        if model and model not in unique:
            unique.append(model)
    return unique


def _error_status_code(exc: Exception) -> int | None:
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _is_retryable_error(exc: Exception) -> bool:
    status_code = _error_status_code(exc)
    if status_code in RETRYABLE_STATUS_CODES:
        return True
    message = str(exc).lower()
    return any(keyword in message for keyword in (
        "unavailable",
        "high demand",
        "resource exhausted",
        "rate limit",
        "temporarily",
        "timeout",
    ))


def _friendly_generation_error(exc: Exception) -> str:
    status_code = _error_status_code(exc)
    if status_code in {429, 503} or "high demand" in str(exc).lower():
        return "Geminiが混雑しています。少し時間をおいてもう一度お試しください。"
    return f"Geminiで問題を生成できませんでした: {exc}"


def _generate_content_with_fallback(*, contents: str, temperature: float,
                                    max_output_tokens: int):
    """Geminiの一時混雑時に短く再試行し、予備モデルへ切り替える。"""
    last_error = None
    for model in _model_candidates():
        for attempt in range(MAX_RETRIES + 1):
            try:
                if model != MODEL_NAME or attempt > 0:
                    print(f"Gemini retry: model={model}, attempt={attempt + 1}")
                return client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        response_mime_type="application/json",
                        max_output_tokens=max_output_tokens,
                    ),
                )
            except errors.APIError as exc:
                last_error = exc
                if not _is_retryable_error(exc):
                    raise RuntimeError(_friendly_generation_error(exc)) from exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_SECONDS)
            except Exception as exc:
                last_error = exc
                if not _is_retryable_error(exc):
                    raise
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_SECONDS)
    raise RuntimeError(_friendly_generation_error(last_error)) from last_error


DIFFICULTY_INSTRUCTIONS = {
    "基礎": "教科書の例題と同じレベル。数字や設定を入れ替えただけの素直な類題にしてください。",
    "標準": "教科書の練習問題レベル。基本を理解していれば解ける、ひねりのない問題にしてください。",
    "応用": "少しひねった問題。複数の手順を組み合わせる必要がある問題を含めてください。元の単元の範囲は守る。",
    "ハイレベル": "中学受験の難関校レベル。発展的思考が必要な問題を中心にしてください。元の単元の範囲は守りつつ、特殊算的な発想を要求してOK。",
}

PROBLEM_TYPE_BLOCKS = {
    "おまかせ": """# 問題タイプ: おまかせ
単元の典型的なパターンに合わせて、自然なバリエーションで出題してください。
計算と文章題が混ざってOK。""",
    "計算問題": """# 問題タイプ: 計算問題（純粋な式のみ）
全問、文章を使わず「式 =」の形式で出してください。

【良い例】
- 「2.3 + 1.8 =」
- 「3/4 × 2/5 =」
- 「12 × 8 =」

【ダメな例】
- 「リンゴが3個、ミカンが5個、合計いくつ？」← 文章題なのでNG
- 「2.3 + 1.8 = ?」← =の後ろに?を付けない
- 「次の計算をしましょう。 2.3 + 1.8 =」← 前置き文を付けない

注意: 単元が「割合」「速さ」「単位量」など、文章なしで計算式だけにできない概念中心の場合のみ、「次の割合を求めましょう。 6 ÷ 30 =」のような最小限の指示文を1問だけ許可。それ以外は式だけ。""",
    "文章題": """# 問題タイプ: 文章題
全問、生活場面（買い物・移動・人数・時間・料理など）を題材にした文章題で出題してください。

【良い例】
- 「太郎さんは時速60kmで走る車に2時間乗りました。何km進みましたか。」
- 「ノート1冊150円で、3冊買いました。代金はいくらですか。」
- 「赤いリボンが2/3m、青いリボンが3/4mあります。合わせて何mですか。」

【ダメな例】
- 「2.3 + 1.8 =」← 計算式だけはNG
- 問題文の末尾に「6 ÷ 30 =」のような数値式を付けるのもNG（文章だけで完結させる）

注意: 何を求めるかを文章で明示。計算式は問題文に含めない。""",
    "穴埋め": """# 問題タイプ: 穴埋め
全問、問題の中に「___」（アンダースコア3つ）の空欄を1つ入れて、空欄に当てはまる数または言葉を答えさせてください。

【良い例】
- 「23 + ___ = 47」 → 答え: 24
- 「分母をそろえることを ___ という。」 → 答え: 通分
- 「3.5 ÷ ___ = 0.5」 → 答え: 7
- 「20%は小数で表すと ___ である。」 → 答え: 0.2

【ダメな例】
- 1問に複数の空欄
- 「___」を使わずただ問いかけるだけ

注意: 必ず1問1空欄、形式は「___」で統一。""",
    "選択問題": """# 問題タイプ: 選択問題（2〜4択）
全問、問題本文とは別に choices フィールドで選択肢を出してください。

【必須フォーマット】
q: "問題本文だけ。選択肢は入れない"
choices: [
  {"label": "あ", "text": "選択肢1"},
  {"label": "い", "text": "選択肢2"},
  {"label": "う", "text": "選択肢3"},
  {"label": "え", "text": "選択肢4"}
]
a: "い: 選択肢2"

【良い例】
q: 「2.3 + 1.8 の答えはどれですか。」
choices: [{"label":"あ","text":"3.1"},{"label":"い","text":"4.1"},{"label":"う","text":"4.0"},{"label":"え","text":"5.1"}]
a: 「い: 4.1」

q: 「リンゴが12個あります。3人で同じ数ずつ分けると、1人何個もらえますか。」
choices: [{"label":"あ","text":"3個"},{"label":"い","text":"4個"},{"label":"う","text":"5個"},{"label":"え","text":"6個"}]
a: 「い: 4個」

【ダメな例】
- 問題本文だけで選択肢がない（必ずNG）
- 選択肢が1つだけ
- qフィールドの中に選択肢を入れて、choices フィールドを空にする
- qフィールドの中に「あ:」「①」などの選択肢を書き込む
- 答えが「い: 4.1」ではなく「い」だけや「4.1」だけ（ラベルと内容が両方必要）

注意:
- 不正解の選択肢は、よくある計算ミスや桁違いを反映する（適当な数字ではなく、生徒が間違えそうな値）
- choices は必ず2〜4個。低学年は「あ・い・う・え」を使う
- 選択肢は短くし、1つの選択肢に複数の文を入れない""",
    "まとめ問題": """# 問題タイプ: まとめ問題（総合問題）
単元全体の知識を組み合わせる総合問題を出してください。1問の中で複数の概念や手順を扱います。

【良い例】
- 「分数」単元: 「1と2/3 + 5/6 を計算して、結果を分数と小数の両方で表しなさい。」
- 「速さ」単元: 「時速60kmで2時間30分走り、その後時速50kmで1時間40分走りました。合計の道のりは何kmですか。」
- 「割合」単元: 「定価2000円の商品を20%引きで買い、さらに会員割引で5%引きになりました。最終的な値段は？」

注意: 1問につき2つ以上の操作（計算・換算・比較・複数手順）を含める。""",
    "ミスしやすい問題": """# 問題タイプ: ミスしやすい問題
小学生がよく間違えるポイントを狙い撃ちする問題を出題してください。

【ミスのパターン例】
- 計算ミス: 繰り上がり/下がり忘れ、桁取り違い
- 単位換算: cm↔m, g↔kg, 分↔秒, 時間↔分の混同
- 概念の混同: 割合の「もとにする量」「くらべる量」、平均の出し方
- 0や1を含む特殊ケース: 「0をかける」「1で割る」
- 小数点の位置: 小数のかけ算で位置を間違える

【良い例】
- 「3.4 × 0.5 =」（小数のかけ算で小数点位置ミス誘発）
- 「1m20cm + 80cm = ___cm」（単位の落とし穴）
- 「定価2000円の20%引きの値段から、さらに10%引き」（重ね掛けの誤解）

注意: 各問題が「どんなミスを狙うか」を意識。簡単すぎず、ひっかけすぎない。""",
}

ANSWER_STYLE_FIELDS = {
    "answer_only": "",
    "with_steps": '\n    "steps": "計算の途中式や式変形を1〜3行で",',
    "with_explanation": '\n    "steps": "計算の途中式や式変形を1〜3行で",\n    "explanation": "解き方の手順と注意点を、その学年の生徒にわかる言葉で4〜6行で説明",',
}

ANSWER_STYLE_INSTRUCTIONS = {
    "answer_only": "答えとヒントのみ。途中式・解説は不要。",
    "with_steps": "答えに加えて、計算の途中式（steps）を簡潔に書いてください。",
    "with_explanation": "答え＋途中式（steps）＋解き方の解説（explanation）。解説はその学年の生徒にわかる言葉で書く。",
}

DIAGRAM_INSTRUCTIONS = """# 図形・測定問題の図
図形、面積、体積、円、角度、平行・垂直など、図がある方が自然な問題では、各 question に任意で "diagram" を追加してください。
計算だけの問題、文章だけで十分な問題には diagram を付けないでください。

diagram で使える type:
- "rectangle": 長方形・正方形
- "triangle": 三角形
- "circle": 円
- "angle": 角
- "parallelogram": 平行四辺形
- "trapezoid": 台形
- "cuboid": 直方体・立方体
- "cylinder": 円柱
- "sphere": 球
- "regular_polygon": 正多角形
- "line": 線分

diagram の例:
- {"type":"rectangle","width_label":"6cm","height_label":"4cm"}
- {"type":"triangle","base_label":"8cm","height_label":"5cm"}
- {"type":"circle","radius_label":"3cm"}
- {"type":"angle","angle_label":"60°"}
- {"type":"cuboid","width_label":"6cm","height_label":"4cm","depth_label":"3cm"}

ルール:
- diagram はJSONオブジェクトだけ。SVG、Markdown、説明文は入れない
- 問題文の数字と diagram のラベルは必ず一致させる
- ラベルは "6cm"、"4cm²"、"60°" のように短く書く
"""


PROMPT_FROM_UNIT = """あなたはココリュウスクール（兵庫県伊丹市・小学生向け算数教室）のベテラン問題作成アシスタントです。
塾の先生が指定した単元・難易度・問題タイプ・解答形式に従って、学習指導要領に沿ったオリジナルの演習問題を作成します。
特定の市販テキストの問題は参照せず、単元の典型的なパターンから自前で生成してください。

# 学年
{grade}（小学{grade_num}年生）

# 単元
{unit_name}

# 単元の目標
{unit_objectives}

# 典型的な問題のパターン（参考）
{unit_examples}

# 難易度
{difficulty}: {difficulty_instruction}

{problem_type_block}

# 解答スタイル
{answer_style_instruction}

# 出力形式（必ずこのJSON形式のみで返す）
{{
  "unit": "{unit_name}",
  "summary": "この単元のポイントを2〜3行で。{grade_num}年生にわかる言葉で",
  "estimated_minutes": 整数,
  "questions": [
    {{
      "q": "問題文（問題タイプの形式に厳密に従うこと）",
      "a": "答え",
      "hint": "解き方のヒント1行"{answer_style_fields}
    }}
  ]
}}

選択問題のときだけ、各 question に "choices": [{"label":"あ","text":"..."}, ...] を追加してください。

{diagram_instructions}

# 普遍ルール（必ず守る）
1. questions の数: ちょうど {num_questions} 問
2. 文章は小学{grade_num}年生が読める言葉で。難しい漢字は使わない
3. 計算式は「2.8 + 1.3 =」のように「=」で終える。「= ?」「=□」「= ___」などは付けない（「穴埋め」タイプを除く）
4. 答えは必ず正確に。手で検算してから出力
5. hint は1行のみ。考え方の入り口だけ示し、答えそのものは書かない
6. 問題どうしは互いに重複しないよう、数字や状況を変える
7. estimated_minutes: 全問解くのに要する目安時間（整数）。基礎=1問1〜2分、標準=1問2〜3分、応用=1問3〜5分、ハイレベル=1問5〜8分
8. JSON以外の余計な文字（説明・前置き・コードフェンス）は一切出力しない
9. 問題タイプの指示が一番優先される。形式が指示と異なる場合は出力を拒否する
"""

PROMPT_TEMPLATE = """あなたはココリュウスクール（兵庫県伊丹市・小学生向け算数教室）の問題作成アシスタントです。
塾の先生が市販テキストを撮影した画像から抽出されたテキストをもとに、
同じ単元で似た形式の演習問題を作成してください。

# 対象学年
{grade}（小学{grade_num}年生）

# 難易度
{difficulty}: {difficulty_instruction}

# 出力形式（必ずこのJSON形式で返す）
{{
  "unit": "この教材の単元名（例: 分数のたし算、小数のかけ算、面積、割合 など）",
  "summary": "この単元のポイントを2〜3行で。{grade_num}年生にわかる言葉で",
  "questions": [
    {{"q": "問題文", "a": "答え", "hint": "解き方のヒント1行"}},
    {{"q": "問題文", "a": "答え", "hint": "解き方のヒント1行"}}
  ]
}}

選択問題のときだけ、各 question に "choices": [{"label":"あ","text":"..."}, ...] を追加してください。

{diagram_instructions}

# ルール
- questions: ちょうど {num_questions} 問
- 問題は元の教材と同じ単元・同じ形式の類題にする（数字や設定だけ変える）
- 文章は小学{grade_num}年生が読める言葉で。難しい漢字は使わない
- 計算問題の書き方: 「2.8 + 1.3 =」のように「=」で終える。「= ?」「=□」「= ___」などは付けない
- 答えは必ず正確に。途中の計算が合っているか確認してから出力
- hint は1行で。考え方の入り口だけ示す（答えは書かない）
- JSON以外の余計な文字は一切出力しない

# 元の教材テキスト
{text}
"""


def generate_problems(text: str, grade: str = "小5", num_questions: int = 8, difficulty: str = "標準") -> dict:
    """市販テキストの問題ページから類題を生成"""
    import re
    m = re.search(r"[1-6]", grade)
    grade_num = m.group() if m else "5"
    difficulty_instruction = DIFFICULTY_INSTRUCTIONS.get(difficulty, DIFFICULTY_INSTRUCTIONS["標準"])

    response = _generate_content_with_fallback(
        contents=PROMPT_TEMPLATE.format(
            text=text,
            grade=grade,
            grade_num=grade_num,
            num_questions=num_questions,
            difficulty=difficulty,
            difficulty_instruction=difficulty_instruction,
            diagram_instructions=DIAGRAM_INSTRUCTIONS,
        ),
        temperature=0.4,
        max_output_tokens=4000,
    )

    raw = (response.text or "").strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON解析エラー: {e}")
        print("生レスポンス:")
        print(raw)
        return {"raw": raw}


def generate_from_units(units: list, grade: str = "小5", num_questions: int = 8,
                         difficulty: str = "標準", answer_style: str = "answer_only",
                         problem_type: str = "おまかせ") -> dict:
    """単一または複数の単元から演習問題を生成する。
    units: dict の単一 or list[dict]。
    """
    if isinstance(units, dict):
        units = [units]
    if len(units) == 1:
        return generate_from_unit(units[0], grade=grade, num_questions=num_questions,
                                   difficulty=difficulty, answer_style=answer_style,
                                   problem_type=problem_type)
    return _generate_from_multi(units, grade=grade, num_questions=num_questions,
                                  difficulty=difficulty, answer_style=answer_style,
                                  problem_type=problem_type)


def _generate_from_multi(units: list, grade: str, num_questions: int,
                          difficulty: str, answer_style: str, problem_type: str) -> dict:
    """複数単元ミックスのプリント生成"""
    import re
    m = re.search(r"[1-6]", grade)
    grade_num = m.group() if m else "5"
    difficulty_instruction = DIFFICULTY_INSTRUCTIONS.get(difficulty, DIFFICULTY_INSTRUCTIONS["標準"])
    answer_style_fields = ANSWER_STYLE_FIELDS.get(answer_style, "")
    answer_style_instruction = ANSWER_STYLE_INSTRUCTIONS.get(answer_style, ANSWER_STYLE_INSTRUCTIONS["answer_only"])
    problem_type_block = PROBLEM_TYPE_BLOCKS.get(problem_type, PROBLEM_TYPE_BLOCKS["おまかせ"])

    units_block = "\n\n".join(
        f"[単元{i}] {u.get('name', '')}\n  目標: {u.get('objectives', '')}\n  例: {u.get('examples', '')}"
        for i, u in enumerate(units, 1)
    )
    unit_titles = "・".join(u.get("name", "") for u in units)
    n_units = len(units)
    per_unit = max(1, num_questions // n_units)

    prompt = f"""あなたはココリュウスクール（兵庫県伊丹市・小学生向け算数教室）のベテラン問題作成アシスタントです。
以下の{n_units}つの単元から、合計{num_questions}問を均等に混ぜた総合演習プリントを作成してください。
特定の市販テキストの問題は参照せず、各単元の典型的なパターンから自前で生成します。

# 学年
{grade}（小学{grade_num}年生）

# 出題する単元一覧
{units_block}

# 難易度
{difficulty}: {difficulty_instruction}

{problem_type_block}

# 解答スタイル
{answer_style_instruction}

# 出力形式（必ずこのJSON形式のみで返す）
{{
  "unit": "{unit_titles} 総合",
  "summary": "今回の総合プリントで扱う単元のポイントを2〜3行で。{grade_num}年生にわかる言葉で",
  "estimated_minutes": 整数,
  "questions": [
    {{
      "q": "問題文",
      "a": "答え",
      "hint": "解き方のヒント1行"{answer_style_fields}
    }}
  ]
}}

# 普遍ルール（必ず守る）
1. questions の数: ちょうど {num_questions} 問
2. 各単元から均等に出題する（だいたい{per_unit}問ずつ）
3. 単元の順番にとらわれず、混ぜて並べる
4. 文章は小学{grade_num}年生が読める言葉で
5. 計算式は「2.8 + 1.3 =」のように「=」で終える（穴埋め型を除く）
6. 答えは必ず正確に、検算してから出力
7. hint は1行のみ
8. estimated_minutes: 全問解くのに要する目安時間（整数）。基礎=1問1〜2分、標準=1問2〜3分、応用=1問3〜5分、ハイレベル=1問5〜8分
9. JSON以外の文字は一切出力しない

{DIAGRAM_INSTRUCTIONS}
"""

    response = _generate_content_with_fallback(
        contents=prompt,
        temperature=0.4,
        max_output_tokens=4500,
    )

    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON解析エラー: {e}")
        return {"raw": raw}


def generate_from_unit(unit: dict, grade: str = "小5", num_questions: int = 8, difficulty: str = "標準", answer_style: str = "answer_only", problem_type: str = "おまかせ") -> dict:
    """学習指導要領ベースの単元データから演習問題を生成する（市販テキスト非依存）

    unit: curriculum.json の1単元エントリ。{name, objectives, examples} を持つ
    answer_style: "answer_only" / "with_steps" / "with_explanation"
    problem_type: "おまかせ" / "計算問題" / "文章題" / "穴埋め" / "選択問題" / "まとめ問題" / "ミスしやすい問題"
    """
    import re
    m = re.search(r"[1-6]", grade)
    grade_num = m.group() if m else "5"
    difficulty_instruction = DIFFICULTY_INSTRUCTIONS.get(difficulty, DIFFICULTY_INSTRUCTIONS["標準"])
    answer_style_fields = ANSWER_STYLE_FIELDS.get(answer_style, "")
    answer_style_instruction = ANSWER_STYLE_INSTRUCTIONS.get(answer_style, ANSWER_STYLE_INSTRUCTIONS["answer_only"])
    problem_type_block = PROBLEM_TYPE_BLOCKS.get(problem_type, PROBLEM_TYPE_BLOCKS["おまかせ"])

    response = _generate_content_with_fallback(
        contents=PROMPT_FROM_UNIT.format(
            grade=grade,
            grade_num=grade_num,
            unit_name=unit.get("name", ""),
            unit_objectives=unit.get("objectives", ""),
            unit_examples=unit.get("examples", ""),
            difficulty=difficulty,
            difficulty_instruction=difficulty_instruction,
            num_questions=num_questions,
            answer_style_fields=answer_style_fields,
            answer_style_instruction=answer_style_instruction,
            problem_type_block=problem_type_block,
            diagram_instructions=DIAGRAM_INSTRUCTIONS,
        ),
        temperature=0.3,
        max_output_tokens=4000,
    )

    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON解析エラー: {e}")
        return {"raw": raw}


def parse_meta(args):
    grade = "小5"
    num_questions = 8
    i = 0
    while i < len(args):
        if args[i] == "--grade" and i + 1 < len(args):
            grade = args[i + 1]
            i += 2
        elif args[i] in ("--n", "--num") and i + 1 < len(args):
            try:
                num_questions = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1
    return grade, num_questions


def main():
    if len(sys.argv) < 2:
        print("使い方:")
        print("  python test_summary.py '教材テキスト' [--grade 小4|小5] [--n 問題数]")
        print("  python test_summary.py @テキストファイルパス [--grade 小4] [--n 6]")
        sys.exit(1)

    arg = sys.argv[1]
    if arg.startswith("@"):
        with open(arg[1:], "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = arg

    grade, num_questions = parse_meta(sys.argv[2:])

    print(f"📝 入力テキスト ({len(text)}文字) / 学年: {grade} / 問題数: {num_questions}")
    print("-" * 60)
    print(text[:200] + ("..." if len(text) > 200 else ""))
    print("-" * 60)
    print(f"🤖 {MODEL_NAME} で類題を生成中...")

    result = generate_problems(text, grade=grade, num_questions=num_questions)

    print("✅ 生成成功")
    print("=" * 60)

    if "questions" in result:
        print(f"📚 単元: {result.get('unit', '（未判定）')}")
        print(f"📌 要点: {result.get('summary', '')}")
        print()
        print("❓ 類題:")
        for i, qa in enumerate(result.get("questions", []), 1):
            print(f"  Q{i}. {qa['q']}")
            print(f"      ヒント: {qa.get('hint', '')}")
            print(f"      答え:   {qa['a']}")
            print()
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
