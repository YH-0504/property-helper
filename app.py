import streamlit as st
import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from PIL import Image
import re
import pandas as pd
import io

st.set_page_config(page_title="房產精耕謄本助手", layout="wide")

st.title("🏡 房產精耕小工具：謄本精準擷取 (座標精確鎖定版)")
st.write("已改用**『地址』關鍵字精準座標鎖定**，徹底解決抓到頁尾雜訊問題，並清除全半形星號！")

uploaded_files = st.file_uploader("請拖曳或上傳建物謄本/電傳 PDF (可複選多個)", type=["pdf"], accept_multiple_files=True)

def get_address_by_coordinates(file_bytes, page_idx=1):
    """ 利用『地址』文字座標精確定位右側區域進行 OCR """
    try:
        # 1. 透過 pdfplumber 尋找第 2 頁「地址」標籤的精確座標 (x0, top, x1, bottom)
        addr_box = None
        pdf_stream = io.BytesIO(file_bytes)
        with pdfplumber.open(pdf_stream) as pdf:
            target_p = pdf.pages[page_idx] if len(pdf.pages) > page_idx else pdf.pages[-1]
            page_w = target_p.width
            page_h = target_p.height
            
            # 尋找所有包含「地」或「址」的字元或字詞
            words = target_p.extract_words()
            for w in words:
                if "地址" in w["text"] or "住址" in w["text"]:
                    addr_box = w
                    break
        
        # 2. 用 pypdfium2 渲染高解析圖片
        pdf_doc = pdfium.PdfDocument(file_bytes)
        target_p_img = pdf_doc[page_idx if len(pdf_doc) > page_idx else len(pdf_doc) - 1]
        scale = 3.0
        pil_img = target_p_img.render(scale=scale).to_pil()
        img_w, img_h = pil_img.size

        # 3. 計算精確裁切區域
        if addr_box:
            # 如果找到「地址」兩字，取它右邊整條（寬度到表格邊界，高度取該列的高度略微放寬）
            scale_x = img_w / page_w
            scale_y = img_h / page_h
            
            x0 = int(addr_box["x1"] * scale_x) + 5  # 地址標籤右邊界再往右一點
            y0 = int((addr_box["top"] - 3) * scale_y)  # 稍微往上抓一點點
            x1 = int(img_w * 0.92)  # 抓到右邊框線前
            y1 = int((addr_box["bottom"] + 5) * scale_y) # 抓取此列高度
            crop_rect = (x0, y0, x1, y1)
        else:
            # 備用保底定位（中間右側）
            crop_rect = (int(img_w * 0.22), int(img_h * 0.28), int(img_w * 0.90), int(img_h * 0.45))

        cropped = pil_img.crop(crop_rect)
        
        # 4. 影像強化與繁中辨識
        gray = cropped.convert('L')
        # 二值化處理：將底色變純白、文字變純黑
        bw = gray.point(lambda x: 0 if x < 180 else 255, '1')
        
        text = pytesseract.image_to_string(bw, lang='chi_tra+eng', config='--psm 7')
        clean_text = re.sub(r"[\s\|\r\n]+", "", text)
        
        # 剔除誤抓的文字標籤雜訊
        clean_text = re.sub(r"^(?:地址|住址)[：:\s]*", "", clean_text)
        
        if any(star in clean_text for star in ["***", "＊＊＊"]) or "隱匿" in clean_text:
            return "隱匿"
        
        # 只要抓到至少3個字且排除頁首頁尾關鍵字
        if len(clean_text) >= 4 and not any(k in clean_text for k in ["查詢時間", "資料來源", "登記次序", "權利範圍"]):
            return clean_text
            
        return "隱匿"
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

    # 全形英數與標點標準化轉換
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

    # 1. 建物門牌 (完整組合)
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

    # 2. 面積計算 (坪數換算)
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

    # 4. 所有權人姓名與性別 (徹底清除半形與全形星號)
    owner_sec = clean_full
    owner_page_idx = 1
    for idx, pt in enumerate(pages_text):
        if "所有權" in pt:
            owner_page_idx = idx
            owner_sec = pt
            break

    raw_name = ""
    name_m = re.search(r"所有權人[：:\s\n]*([^\d\n\r\s]+)", owner_sec)
    if name_m:
        # 同時移除半形 '*' 與全形 '＊'
        raw_name = re.sub(r"[\*＊]+", "", name_m.group(1)).strip()

    title = ""
    id_m = re.search(r"([A-Za-z])\s*([12])[\d\*＊]{2,}", owner_sec)
    if id_m:
        code = id_m.group(2)
        if code == "1":
            title = "先生"
        elif code == "2":
            title = "女士"

    if raw_name:
        data["所有權人"] = raw_name + title

    # 5. 戶籍地址 (透過文字座標精準鎖定)
    data["戶籍地址"] = get_address_by_coordinates(file_bytes, page_idx=owner_page_idx)

    return data

# 介面展示
if uploaded_files:
    results = []
    with st.spinner(f"正在透過座標定位解析 {len(uploaded_files)} 份物件資料..."):
        for f in uploaded_files:
            try:
                info = parse_transcript_fast(f)
                results.append(info)
            except Exception as e:
                st.error(f"檔案 {f.name} 處理失敗：{e}")

    if results:
        st.success(f"✅ 成功整理 {len(results)} 筆精耕資料！")
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
