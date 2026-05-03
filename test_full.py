"""
ManaCam for KOKORYUSCHOOL - フルパイプライン
画像 → OCR → 類題生成 → PDF出力（生徒配布用＋先生用解答）

使い方:
  python test_full.py 画像ファイルパス [--grade 小4|小5] [--n 8]
"""
import sys
from pathlib import Path
from datetime import datetime

from test_ocr import ocr_image
from test_summary import generate_problems, parse_meta
from make_pdf import make_pdf


OUTPUT_DIR = Path(__file__).parent / "output"


def main():
    if len(sys.argv) < 2:
        print('使い方: python test_full.py <画像> [--grade 小4|小5] [--n 8]')
        sys.exit(1)

    image_path = sys.argv[1]
    grade, num_questions = parse_meta(sys.argv[2:])

    print("=" * 60)
    print("🏫 ココリュウスクール ManaCam")
    print(f"   学年: {grade} / 問題数: {num_questions}")
    print("=" * 60)

    print("📸 STEP 1: OCR（画像→テキスト）")
    text = ocr_image(image_path)
    if not text:
        print("❌ OCR失敗")
        sys.exit(1)
    print(f"✅ {len(text)}文字を抽出")
    print()

    print("🤖 STEP 2: 類題を生成")
    result = generate_problems(text, grade=grade, num_questions=num_questions)
    print()

    print("=" * 60)
    print("📚 生成結果")
    print("=" * 60)
    if "questions" in result:
        print(f"単元: {result.get('unit', '?')}")
        print(f"要点: {result.get('summary', '')}")
        print()
        print("類題:")
        for i, qa in enumerate(result.get("questions", []), 1):
            print(f"  ({i}) {qa.get('q', '')}")
            print(f"       答え: {qa.get('a', '')}")
        print()
    else:
        print(result)
        sys.exit(1)

    print("📄 STEP 3: PDF出力")
    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unit_safe = (result.get("unit") or "untitled").replace("/", "_")
    pdf_path = OUTPUT_DIR / f"{stamp}_{grade}_{unit_safe}.pdf"
    saved = make_pdf(result, pdf_path, grade=grade)
    print(f"✅ PDF: {saved.resolve()}")
    print("   1枚目: 生徒配布用 / 2枚目: 先生用解答＋ヒント")
    print("=" * 60)


if __name__ == "__main__":
    main()
