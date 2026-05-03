"""
ManaCam - OCR動作確認スクリプト
Google Cloud Vision APIで画像から日本語テキストを抽出する
"""
import os
import sys
import base64
import json
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

API_KEY = os.getenv("GOOGLE_VISION_API_KEY")
if not API_KEY or API_KEY == "ここに貼り付け":
    print("❌ GOOGLE_VISION_API_KEY が設定されていません")
    print("   .env ファイルを編集してください")
    sys.exit(1)


def ocr_image(image_path: str) -> str:
    """画像ファイルからテキストを抽出"""
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"画像が見つかりません: {image_path}")

    with open(image_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    url = f"https://vision.googleapis.com/v1/images:annotate?key={API_KEY}"
    payload = {
        "requests": [{
            "image": {"content": content},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["ja"]}
        }]
    }

    response = requests.post(url, json=payload, timeout=30)
    if response.status_code != 200:
        print(f"❌ HTTPエラー {response.status_code}")
        try:
            err = response.json()
            print("API応答:")
            print(json.dumps(err, ensure_ascii=False, indent=2))
        except Exception:
            print(response.text)
        sys.exit(1)

    data = response.json()
    if "responses" not in data or not data["responses"]:
        return ""

    result = data["responses"][0]
    if "error" in result:
        raise RuntimeError(f"Vision API エラー: {result['error']}")

    return result.get("fullTextAnnotation", {}).get("text", "")


def main():
    if len(sys.argv) < 2:
        print("使い方: python test_ocr.py <画像ファイルパス>")
        print("例: python test_ocr.py test_images/textbook.jpg")
        sys.exit(1)

    image_path = sys.argv[1]
    print(f"📸 画像を解析中: {image_path}")
    print("-" * 60)

    text = ocr_image(image_path)

    if not text:
        print("⚠️ テキストが検出されませんでした")
        return

    print("✅ OCR成功")
    print("-" * 60)
    print(text)
    print("-" * 60)
    print(f"📊 文字数: {len(text)}")


if __name__ == "__main__":
    main()
