import streamlit as st
import pdfplumber
import pypdfium2 as pdfium
from google import genai
from google.genai import types
from PIL import Image
import re
import pandas as pd
import io
import time

st.set_page_config(page_title="房產精耕謄本助手", layout="wide")

st.title("🏡 房產精耕小工具：謄本精準擷取")
st.write("已強化：**所有權人稱謂鎖定**、**地址小區塊自動裁切極速辨識**！")

# 讀取 API Key (優先從 Secrets 抓，若無則在側邊欄輸入)
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("請輸入 Google Gemini API Key", type="password")

uploaded_files = st.file_uploader("請拖曳或上傳建物謄本/電傳 PDF (可複選多個)", type=["pdf"], accept_multiple_files=True)

def ocr_address_cropped(file_bytes, page_idx=1):
    """ 只裁切地址區域的小圖給 AI 辨識，速度提升 10 倍，避免超時 """
    if not api_key:
        return "未填 API Key"
    
    try:
        pdf = pdfium.PdfDocument(file_bytes)
        target_idx = page_idx if len(pdf) > page_idx else len(pdf) - 1
        page = pdf[target_idx]
        
        # 渲染整頁圖片
        img = page.render(scale=2.0).to_pil()
        w, h = img.size
        
        # 華安電傳「地址」大約位於所有權部表格的上方 30%~55% 處
        # 進行針對性垂直範圍裁切，大幅縮小傳輸體積
        crop_box = (int(w * 0.15), int(h * 0.30), int(w * 0.95), int(h * 0.58))
        cropped_img = img.crop(crop_box)
        
        img_byte_arr = io.BytesIO()
        cropped_img.save(img_byte_arr, format='JPEG', quality=85)
        img_bytes = img_byte_arr.getvalue()

        client = genai.Client(api_key=api_key)
        prompt = "這是一張建物謄本局部截圖。請辨識圖中『地址』那一行所記載的地址。如果被星號隱匿請只回覆『隱匿』。請直接輸出地址內容，不要有其他任何文字。"

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
                res_text = res_text.replace("\n", "").replace("`", "").replace("地址", "").replace("：", "").replace(":", "").strip()
                return res_text if len(res_text) > 1 else "隱匿"
            except Exception as e:
                time.sleep(1.5)
                continue
        return "AI辨識超時"
    except Exception as e:
        return "辨識錯誤"

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

    # 1. 建物完整門牌
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
            if region_match and region_match.group(2) in raw_doorplate:
                data["建物門牌"] = f"{region_match.group(1)}{raw_doorplate}"
            else:
                data["建物門牌"] = f"{city_district}{raw_doorplate}"

    # 2. 面積計算
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

    # 4. 所有權人姓名與性別 (強化跨行與電傳排版精準定位)
    owner_sec = clean_full
    owner_page_idx = 1
    for idx, pt in enumerate(pages_text):
        if "所有權" in pt:
            owner_page_idx = idx
            owner_sec = pt
            break

    # 姓氏提取：找「所有權人」這四個字之後的第一個中文字
    raw_name = ""
    # 支援：所有權人 王**、所有權人\n甘**
    name_m = re.search(r"所有權人[：:\s\n]*([^\d\n\r\s\*]{1,3})[\*]*", owner_sec)
    if name_m:
        raw_name = name_m.group(1).strip()

    # 性別判定：抓身分證第 2 碼（英文字母後的 1 或 2）
    title = ""
    id_m = re.search(r"([A-Za-z])\s*([12])[\d\*]{2,}", owner_sec)
    if id_m:
        code = id_m.group(2)
        if code == "1":
            title = "先生"
        elif code == "2":
            title = "女士"

    if raw_name:
        data["所有權人"] = raw_name + title

    # 5. 戶籍地址：先試本地是否有文字，若無則精準裁切送 AI
    # 本地文字嘗試
    local_addr_m = re.search(r"(?:地址|住址)[：:\s\n]*([^\n\r]+)", owner_sec)
    got_local = False
    if local_addr_m:
        cand = local_addr_m.group(1).strip()
        cand = re.split(r"(?:權利範圍|統一編號|權狀字號)", cand)[0].strip()
        if any(w in cand for w in ["市", "縣", "鄉", "鎮", "區", "路", "街", "巷"]):
            data["戶籍地址"] = cand
            got_local = True

    # 本地沒撈到正常地址，才啟動 AI 小圖裁切辨識
    if not got_local:
        data["戶籍地址"] = ocr_address_cropped(file_bytes, page_idx=owner_page_idx)

    return data

# 介面展示
if uploaded_files:
    results = []
    with st.spinner(f"正在精準解析 {len(uploaded_files)} 份物件資料..."):
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
