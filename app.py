import streamlit as st
import pdfplumber
import pypdfium2 as pdfium
from google import genai
from google.genai import types
import re
import pandas as pd
import io
import time

st.set_page_config(page_title="房產精耕謄本助手", layout="wide")

st.title("🏡 房產精耕小工具：謄本精準擷取 (輕量混合高速版)")
st.write("坪數與門牌由本地極速處理，**AI 僅專注辨識第 2 頁戶籍地址**，大幅縮短運算時間！")

# 讀取 API Key (優先從 Secrets 抓，若無則在側邊欄輸入)
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("請輸入 Google Gemini API Key", type="password")

uploaded_files = st.file_uploader("請拖曳或上傳建物謄本/電傳 PDF (可複選多個)", type=["pdf"], accept_multiple_files=True)

def ocr_address_only(file_bytes, page_index=1):
    """ 只將第 2 頁（索引為1）轉成圖片送給 AI 辨識地址那一欄 """
    if not api_key:
        return "未填 API Key"
    
    try:
        pdf = pdfium.PdfDocument(file_bytes)
        target_idx = page_index if len(pdf) > page_index else len(pdf) - 1
        page = pdf[target_idx]
        
        # 轉成圖片
        image = page.render(scale=1.5).to_pil()
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='JPEG', quality=85)
        img_bytes = img_byte_arr.getvalue()

        client = genai.Client(api_key=api_key)
        
        # 極簡 Prompt，要求只讀地址那一欄
        prompt = "請看這張建物所有權部圖片，精準讀出「地址」欄位中的文字。若有星號隱匿請回覆「隱匿」。請直接輸出地址本身，不要有其他字眼。"

        # 自動重試機制
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg'),
                        prompt
                    ]
                )
                res_text = response.text.strip()
                # 剔除可能的多餘字元
                res_text = res_text.replace("\n", "").replace("`", "")
                return res_text if res_text else "隱匿"
            except Exception as e:
                if attempt < 2:
                    time.sleep(1.5)
                    continue
                return "AI辨識超時"
    except Exception as e:
        return "讀取錯誤"

def parse_transcript_fast(file):
    file_bytes = file.read()
    file_stream = io.BytesIO(file_bytes)

    pages_text = []
    with pdfplumber.open(file_stream) as pdf:
        for p in pdf.pages:
            t = p.extract_text()
            pages_text.append(t if t else "")

    full_text = "\n".join(pages_text)

    # 全形轉半形
    half_text = ""
    for char in full_text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            half_text += chr(code - 0xFEE0)
        elif code == 0x3000:
            half_text += " "
        else:
            half_text += char

    clean_full = re.sub(r"[\|\t]", " ", half_text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in clean_full.split("\n") if line.strip()]

    data = {
        "建物門牌": "未識別",
        "總坪數": 0.0,
        "主建物(坪)": 0.0,
        "附屬(坪)": 0.0,
        "公設(坪)": 0.0,
        "車位標示": "無/未標示",
        "所有權人": "未識別",
        "戶籍地址": "抓取錯誤"
    }

    # 1. 建物完整門牌 (補齊 臺南市東區 等)
    city_district = ""
    region_match = re.search(r"([^\d\n\r\s]{2,3}(?:市|縣))\s*([^\d\n\r\s]{1,4}(?:區|鄉|鎮|市))", clean_full)
    if region_match:
        city_district = region_match.group(1).replace(" ", "") + region_match.group(2).replace(" ", "")

    raw_doorplate = ""
    for i, line in enumerate(lines):
        if "建物門牌" in line:
            after_label = re.sub(r"^.*?建物門牌[：:\s]*", "", line).strip()
            if len(after_label) > 1:
                raw_doorplate = after_label
                break
            elif i + 1 < len(lines):
                raw_doorplate = lines[i+1].strip()
                break

    raw_doorplate = raw_doorplate.replace(" ", "")
    if raw_doorplate:
        if any(c in raw_doorplate for c in ["市", "縣"]):
            data["建物門牌"] = raw_doorplate
        else:
            prefix = city_district
            if region_match and region_match.group(2) in raw_doorplate:
                data["建物門牌"] = f"{region_match.group(1)}{raw_doorplate}"
            else:
                data["建物門牌"] = f"{prefix}{raw_doorplate}"

    # 2. 面積計算 (主建、附屬、公設、總坪數)
    main_m2 = 0.0
    main_match = re.search(r"層次面積\s*([\d\.]+)\s*平方公尺", clean_full)
    if main_match:
        main_m2 = float(main_match.group(1))
    data["主建物(坪)"] = round(main_m2 * 0.3025, 2)

    sub_m2 = 0.0
    sub_matches = re.findall(r"(?:陽台|露台|雨遮|平台|花台)[^\d\n\r]*?面積\s*([\d\.]+)\s*平方公尺", clean_full)
    if sub_matches:
        sub_m2 = sum([float(m) for m in sub_matches])
    data["附屬(坪)"] = round(sub_m2 * 0.3025, 2)

    pub_m2 = 0.0
    linear_text = clean_full.replace("\n", " ")
    pub_matches = re.findall(r"建號\s*([\d\.]+)\s*平方公\s*尺.*?權利範圍\s*(\d+)\s*分之\s*(\d+)", linear_text)
    for p_area, denom, numer in pub_matches:
        try:
            pub_m2 += float(p_area) * (float(numer) / float(denom))
        except:
            pass
    data["公設(坪)"] = round(pub_m2 * 0.3025, 2)
    data["總坪數"] = round(data["主建物(坪)"] + data["附屬(坪)"] + data["公設(坪)"], 2)

    # 3. 車位標示
    parking_match = re.search(r"(?:編號|車位)[：:\s]*([A-Za-z0-9\-\_]+号|[A-Za-z0-9\-\_]+號|[B|b]\d+[\s\-]*(?:號)?\d*)", clean_full)
    if not parking_match:
        parking_match = re.search(r"(地下一層|地下二層|地下三層|地下四層|地下五層|B[1-5])[^\n\r]*?(?:車位|編號)[：:\s]*([^\n\r\s]+)", clean_full)
        if parking_match:
            data["車位標示"] = f"{parking_match.group(1)} {parking_match.group(2)}"
    else:
        data["車位標示"] = parking_match.group(1).strip()

    # 4. 所有權人姓名 + 稱謂 (1先生 / 2女士)
    owner_sec = clean_full
    owner_page_idx = 1
    for idx, pt in enumerate(pages_text):
        if "建物所有權部" in pt:
            owner_page_idx = idx
            owner_sec = pt
            break

    raw_name = ""
    name_match = re.search(r"所有權人\s*\n\s*([^\n\r]+)", owner_sec)
    if name_match:
        raw_name = name_match.group(1).replace("*", "").strip()

    title = ""
    id_match = re.search(r"([A-Za-z])\s*([12])\s*[\d\*]{2,}", owner_sec)
    if id_match:
        code = id_match.group(2)
        if code == "1":
            title = "先生"
        elif code == "2":
            title = "女士"

    if raw_name:
        data["所有權人"] = raw_name + title

    # 5. 戶籍地址：精準只呼叫 AI 辨識第 2 頁的那行文字
    data["戶籍地址"] = ocr_address_only(file_bytes, page_index=owner_page_idx)

    return data

# 介面展示
if uploaded_files:
    results = []
    with st.spinner(f"正在秒級整理 {len(uploaded_files)} 份謄本資料..."):
        for f in uploaded_files:
            try:
                info = parse_transcript_fast(f)
                results.append(info)
            except Exception as e:
                st.error(f"檔案 {f.name} 處理失敗：{e}")

    if results:
        st.success(f"✅ 成功整理 {len(results)} 筆資料！")
        df = pd.DataFrame(results)

        columns_to_show = [
            "建物門牌", "總坪數", "主建物(坪)", "附屬(坪)", "公設(坪)",
            "車位標示", "所有權人", "戶籍地址"
        ]
        df = df[columns_to_show]

        st.subheader("📋 精耕物件清單")
        st.dataframe(df, use_container_width=True)

        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 匯出精耕清單 (Excel CSV)",
            data=csv_data,
            file_name="精耕物件清單.csv",
            mime="text/csv"
        )
